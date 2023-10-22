# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
# pylint: disable=missing-module-docstring, invalid-name
from __future__ import annotations

from ipaddress import (
    IPv4Network,
    IPv6Network,
    IPv4Address,
    IPv6Address,
    ip_network,
)
import flask
import werkzeug

from searx.tools import config
from searx import logger

logger = logger.getChild('botdetection')


def dump_request(request: flask.Request):
    return (
        (
            (
                (
                    (
                        (
                            (
                                (
                                    f"{request.path} || X-Forwarded-For: {request.headers.get('X-Forwarded-For')}"
                                    + f" || X-Real-IP: {request.headers.get('X-Real-IP')}"
                                )
                                + f" || form: {request.form}"
                            )
                            + f" || Accept: {request.headers.get('Accept')}"
                        )
                        + f" || Accept-Language: {request.headers.get('Accept-Language')}"
                    )
                    + f" || Accept-Encoding: {request.headers.get('Accept-Encoding')}"
                )
                + f" || Content-Type: {request.headers.get('Content-Type')}"
            )
            + f" || Content-Length: {request.headers.get('Content-Length')}"
        )
        + f" || Connection: {request.headers.get('Connection')}"
    ) + f" || User-Agent: {request.headers.get('User-Agent')}"


def too_many_requests(network: IPv4Network | IPv6Network, log_msg: str) -> werkzeug.Response | None:
    """Returns a HTTP 429 response object and writes a ERROR message to the
    'botdetection' logger.  This function is used in part by the filter methods
    to return the default ``Too Many Requests`` response.

    """

    logger.debug("BLOCK %s: %s", network.compressed, log_msg)
    return flask.make_response(('Too Many Requests', 429))


def get_network(real_ip: IPv4Address | IPv6Address, cfg: config.Config) -> IPv4Network | IPv6Network:
    """Returns the (client) network of whether the real_ip is part of."""

    if real_ip.version == 6:
        prefix = cfg['real_ip.ipv6_prefix']
    else:
        prefix = cfg['real_ip.ipv4_prefix']
    return ip_network(f"{real_ip}/{prefix}", strict=False)


_logged_errors = []


def _log_error_only_once(err_msg):
    if err_msg not in _logged_errors:
        logger.error(err_msg)
        _logged_errors.append(err_msg)


def get_real_ip(request: flask.Request) -> str:
    """Returns real IP of the request.  Since not all proxies set all the HTTP
    headers and incoming headers can be faked it may happen that the IP cannot
    be determined correctly.

    .. sidebar:: :py:obj:`flask.Request.remote_addr`

       SearXNG uses Werkzeug's ProxyFix_ (with it default ``x_for=1``).

    This function tries to get the remote IP in the order listed below,
    additional some tests are done and if inconsistencies or errors are
    detected, they are logged.

    The remote IP of the request is taken from (first match):

    - X-Forwarded-For_ header
    - `X-real-IP header <https://github.com/searxng/searxng/issues/1237#issuecomment-1147564516>`__
    - :py:obj:`flask.Request.remote_addr`

    .. _ProxyFix:
       https://werkzeug.palletsprojects.com/middleware/proxy_fix/

    .. _X-Forwarded-For:
      https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Forwarded-For

    """

    forwarded_for = request.headers.get("X-Forwarded-For")
    real_ip = request.headers.get('X-Real-IP')
    remote_addr = request.remote_addr
    # logger.debug(
    #     "X-Forwarded-For: %s || X-Real-IP: %s || request.remote_addr: %s", forwarded_for, real_ip, remote_addr
    # )

    if not forwarded_for:
        _log_error_only_once("X-Forwarded-For header is not set!")
    else:
        from .limiter import get_cfg  # pylint: disable=import-outside-toplevel, cyclic-import

        forwarded_for = [x.strip() for x in forwarded_for.split(',')]
        x_for: int = get_cfg()['real_ip.x_for']  # type: ignore
        forwarded_for = forwarded_for[-min(len(forwarded_for), x_for)]

    if not real_ip:
        _log_error_only_once("X-Real-IP header is not set!")

    if forwarded_for and real_ip and forwarded_for != real_ip:
        logger.warning("IP from X-Real-IP (%s) is not equal to IP from X-Forwarded-For (%s)", real_ip, forwarded_for)

    if forwarded_for and remote_addr and forwarded_for != remote_addr:
        logger.warning(
            "IP from WSGI environment (%s) is not equal to IP from X-Forwarded-For (%s)", remote_addr, forwarded_for
        )

    if real_ip and remote_addr and real_ip != remote_addr:
        logger.warning("IP from WSGI environment (%s) is not equal to IP from X-Real-IP (%s)", remote_addr, real_ip)

    return forwarded_for or real_ip or remote_addr or '0.0.0.0'

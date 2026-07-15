"""Shared HTTP hardening for alpaca-py clients.

alpaca-py's internal `requests.Session` calls carry NO timeout at all (confirmed
in `alpaca.common.rest.RESTClient._one_request`, which calls
`self._session.request(method, url, **opts)` with no `timeout` key). requests
treats a missing timeout as "wait forever" on the socket read.

That's exactly what caused the bot to silently freeze for 3 days on 2026-07-03:
one call stalled mid-read (no exception, no timeout, no crash) and the process
just sat there "alive" forever, which meant launchd's KeepAlive never noticed
anything was wrong.

`harden()` monkeypatches a client's underlying session so every request it
makes always carries an explicit (connect, read) timeout, turning a silent
infinite hang into a normal, catchable `requests.exceptions.Timeout` within
seconds.
"""
from __future__ import annotations

import functools

# (connect_timeout, read_timeout) in seconds. Kept short-ish so a full
# worst-case scan (all instruments timing out at once, e.g. a real network
# outage) stays bounded to single-digit minutes instead of hours.
DEFAULT_TIMEOUT = (5, 15)


def harden(client: object, timeout: tuple[float, float] = DEFAULT_TIMEOUT) -> None:
    """Force a default timeout onto an alpaca-py client's internal session.

    Safe to call multiple times / on any object; no-ops if the client doesn't
    expose the expected `_session` (e.g. a future alpaca-py version).
    """
    session = getattr(client, "_session", None)
    if session is None or not hasattr(session, "request"):
        return
    session.request = functools.partial(session.request, timeout=timeout)

"""A cache in front of api.met.no, following MET's own rules.

MET's terms ask each client to be a "local proxy". It must never ask again before
`Expires`, must then ask with `If-Modified-Since`, and must cut traffic at once on
a 429. See ADR-WM-001.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import httpx

log = logging.getLogger(__name__)

#: How long to hold off after a 429 that gives no Retry-After.
HOLD_OFF = dt.timedelta(minutes=10)


class UpstreamError(Exception):
    """The service answered with a status this plugin cannot use."""

    def __init__(self, status: int) -> None:
        """Keep the status, so the caller can say what went wrong."""
        super().__init__(f"the service answered {status}")
        self.status = status


class RefusedError(UpstreamError):
    """A 403: MET will not answer this client, most often for its User-Agent."""

    def __init__(self) -> None:
        """A 403 is always the status."""
        super().__init__(403)


class SlowedDownError(UpstreamError):
    """A 429 with nothing kept to answer from."""

    def __init__(self) -> None:
        """A 429 is always the status."""
        super().__init__(429)


@dataclass(frozen=True)
class Answer:
    """What the cache gives back, and how old it is."""

    data: Any
    fetched: dt.datetime
    slowed: bool = False


@dataclass
class _Kept:
    data: Any
    fetched: dt.datetime
    expires: dt.datetime
    last_modified: str | None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _expires(response: httpx.Response, now: dt.datetime) -> dt.datetime:
    value = response.headers.get("expires")
    if not value:
        return now
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return now
    # A "-0000" zone parses to a time with none; HTTP dates are always UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _hold_off(response: httpx.Response, now: dt.datetime) -> dt.datetime:
    after = response.headers.get("retry-after", "")
    return now + (dt.timedelta(seconds=int(after)) if after.isdigit() else HOLD_OFF)


def _slowed(kept: _Kept | None) -> Answer:
    """What a slowed-down ask gets: the forecast kept, marked as old, or nothing."""
    # RULE: a 429 answers from the cache
    if kept is None:
        raise SlowedDownError
    return Answer(kept.data, kept.fetched, slowed=True)


class CachedClient:
    """GETs JSON, answering from what it holds whenever MET's rules say to."""

    def __init__(
        self, http: httpx.AsyncClient, user_agent: str, clock: Callable[[], dt.datetime] = _now
    ) -> None:
        """Wrap an open client; every request carries the given User-Agent."""
        self._http, self._agent, self._clock = http, user_agent, clock
        self._kept: dict[str, _Kept] = {}
        #: Until when MET asked us to stop asking; it covers every point, not one.
        self._held_until: dt.datetime | None = None

    async def get_json(self, url: str, params: Mapping[str, str]) -> Answer:
        """The JSON at url, from the cache when it is still current."""
        key = url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        kept, now = self._kept.get(key), self._clock()
        # RULE: nothing is asked again before it expires
        if kept is not None and now < kept.expires:
            return Answer(kept.data, kept.fetched)
        # RULE: a 429 holds off every request until it ends
        if self._held_until is not None and now < self._held_until:
            return _slowed(kept)
        headers = {"User-Agent": self._agent}
        # RULE: a repeat after expiry asks with if modified since
        if kept is not None and kept.last_modified:
            headers["If-Modified-Since"] = kept.last_modified
        response = await self._http.get(url, params=dict(params), headers=headers)
        status = response.status_code
        if status == 304 and kept is not None:  # noqa: PLR2004 - HTTP's own number
            kept.expires = _expires(response, now)
            return Answer(kept.data, kept.fetched)
        if status == 429:  # noqa: PLR2004 - HTTP's own number
            self._held_until = _hold_off(response, now)
            log.warning("MET asked us to slow down until %s", f"{self._held_until:%H:%M} UTC")
            return _slowed(kept)
        if status == 203:  # noqa: PLR2004 - HTTP's own number
            log.warning("deprecated or beta product: %s", url)
        if status == 403:  # noqa: PLR2004 - HTTP's own number
            log.error("MET refused the request; check the contact in the config")
            raise RefusedError
        if status not in {200, 203}:
            raise UpstreamError(status)
        data = response.json()
        self._kept[key] = _Kept(data, now, _expires(response, now), response.headers.get("last-modified"))
        return Answer(data, now)

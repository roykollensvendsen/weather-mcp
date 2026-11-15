"""A cache in front of api.met.no, following MET's own rules.

MET's terms ask each client to be a "local proxy". It must never ask again before
`Expires`, must then ask with `If-Modified-Since`, and must cut traffic at once on
a 429. See ADR-WM-001.

What it holds is kept in a file, so a restart neither forgets a forecast's
expiry nor a pause MET asked for.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import email.utils
import json
import logging
import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import httpx

log = logging.getLogger(__name__)

#: How long to hold off after a 429 that gives no Retry-After.
HOLD_OFF = dt.timedelta(minutes=10)
#: The longest pause kept, whatever Retry-After says. A mistaken header must not
#: silence the weather for days.
LONGEST_HOLD_OFF = dt.timedelta(hours=1)


def cache_path() -> pathlib.Path:
    """Where forecasts are kept between runs, under the user's cache folder."""
    base = os.environ.get("XDG_CACHE_HOME") or str(pathlib.Path.home() / ".cache")
    return pathlib.Path(base) / "weather-mcp" / "forecasts.json"


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
    """Until when to stop asking: Retry-After as seconds or as a date, at most an hour."""
    after = response.headers.get("retry-after", "").strip()
    until = now + HOLD_OFF
    if after.isdigit():
        seconds = int(after)
        until = now + dt.timedelta(seconds=min(seconds, int(LONGEST_HOLD_OFF.total_seconds())))
    elif after:
        with contextlib.suppress(TypeError, ValueError):
            parsed = email.utils.parsedate_to_datetime(after)
            until = parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    # RULE: a hold off lasts at most an hour
    if until > now + LONGEST_HOLD_OFF:
        log.warning("MET asked for a pause past an hour; holding off for an hour instead")
        until = now + LONGEST_HOLD_OFF
    return until


def _slowed(kept: _Kept | None) -> Answer:
    """What a slowed-down ask gets: the forecast kept, marked as old, or nothing."""
    # RULE: a 429 answers from the cache
    if kept is None:
        raise SlowedDownError
    return Answer(kept.data, kept.fetched, slowed=True)


class CachedClient:
    """GETs JSON, answering from what it holds whenever MET's rules say to."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        user_agent: str,
        clock: Callable[[], dt.datetime] = _now,
        store: pathlib.Path | None = None,
    ) -> None:
        """Wrap an open client; every request carries the given User-Agent.

        With a store, what the cache holds is read from it now and written to it
        after every change. Without one, it lives in memory only.
        """
        self._http, self._agent, self._clock, self._store = http, user_agent, clock, store
        self._kept: dict[str, _Kept] = {}
        #: Until when MET asked us to stop asking; it covers every point, not one.
        self._held_until: dt.datetime | None = None
        # RULE: a restart keeps what the cache held
        self._load()

    def _load(self) -> None:
        if self._store is None or not self._store.is_file():
            return
        try:
            raw = json.loads(self._store.read_bytes())
            kept = {
                key: _Kept(
                    entry["data"],
                    dt.datetime.fromisoformat(entry["fetched"]),
                    dt.datetime.fromisoformat(entry["expires"]),
                    entry.get("last_modified"),
                )
                for key, entry in raw["kept"].items()
            }
            held = raw.get("held_until")
            held_until = dt.datetime.fromisoformat(held) if held else None
        except (ValueError, KeyError, TypeError, AttributeError):
            log.warning("the forecast cache file was damaged; starting afresh")
            return
        self._kept, self._held_until = kept, held_until

    def _save(self) -> None:
        """Write what the cache holds, readable by the owner only, never half-written."""
        if self._store is None:
            return
        body = {
            "held_until": self._held_until.isoformat() if self._held_until else None,
            "kept": {
                key: {
                    "data": k.data,
                    "fetched": k.fetched.isoformat(),
                    "expires": k.expires.isoformat(),
                    "last_modified": k.last_modified,
                }
                for key, k in self._kept.items()
            },
        }
        # RULE: a failed save never stops an answer
        try:
            self._write(json.dumps(body).encode())
        except OSError as failure:
            # The kind and the file, never the message; the answer goes on.
            log.warning(
                "could not save the forecast cache (%s); check that %s is writable",
                type(failure).__name__,
                self._store,
            )

    def _write(self, body: bytes) -> None:
        """Replace the file in one step, from a temporary file of this writer's own."""
        assert self._store is not None  # noqa: S101 - _save checked it
        self._store.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self._store.parent, prefix=".forecasts-", suffix=".part")
        part = pathlib.Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(body)
                file.flush()
                os.fsync(file.fileno())
            part.replace(self._store)
        except BaseException:
            with contextlib.suppress(OSError):
                part.unlink()
            raise

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
            self._save()
            return Answer(kept.data, kept.fetched)
        if status == 429:  # noqa: PLR2004 - HTTP's own number
            self._held_until = _hold_off(response, now)
            log.warning("MET asked us to slow down until %s", f"{self._held_until:%H:%M} UTC")
            self._save()
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
        self._save()
        return Answer(data, now)

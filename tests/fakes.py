"""A fake MET Norway and a fake Kartverket, behind httpx.MockTransport.

They copy the real limits the tests lean on (MET's terms, read 2026-11-14):
a 403 for a missing or generic User-Agent, a 403 for more than four decimals,
`Expires` and `Last-Modified` on every forecast, a 304 after a matching
`If-Modified-Since`, and a 429 when told to slow down.

Every place is made up, near 61.00 N 9.00 E.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import json
import zoneinfo
from dataclasses import dataclass, field

import httpx

START = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.UTC)
LAST_MODIFIED = "Sat, 14 Nov 2026 11:30:00 GMT"
FORECAST_PATH = "/weatherapi/locationforecast/2.0/compact"
PLACES_PATH = "/stedsnavn/v1/sted"


@dataclass
class Clock:
    """Time the test moves by hand, shared by the fake and the client."""

    now: dt.datetime = START

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now += dt.timedelta(minutes=minutes)


def forecast(temperature: float = 7.0, symbol: str = "cloudy", rain: float = 0.0) -> dict[str, object]:
    """A compact forecast with the fields this plugin reads."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [9.0, 61.0, 500]},
        "properties": {
            "meta": {"updated_at": "2026-11-14T11:30:00Z"},
            "timeseries": [
                {
                    "time": "2026-11-14T12:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": temperature, "wind_speed": 3.2}},
                        "next_1_hours": {
                            "summary": {"symbol_code": symbol},
                            "details": {"precipitation_amount": rain},
                        },
                    },
                }
            ],
        },
    }


def hourly(at, start: dt.datetime = START, hours: int = 60) -> dict[str, object]:
    """A forecast an hour apart, as MET gives for the first days.

    `at(local)` gives temperature, symbol, rain and wind for each hour, by Oslo time.
    """
    oslo = zoneinfo.ZoneInfo("Europe/Oslo")
    series = []
    for n in range(hours):
        time = start + dt.timedelta(hours=n)
        temperature, symbol, rain, wind = at(time.astimezone(oslo))
        series.append(
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "instant": {"details": {"air_temperature": temperature, "wind_speed": wind}},
                    "next_1_hours": {
                        "summary": {"symbol_code": symbol},
                        "details": {"precipitation_amount": rain},
                    },
                },
            }
        )
    body = forecast()
    body["properties"]["timeseries"] = series  # type: ignore[index]
    return body


#: Kartverket's type codes, which its /sted filter takes (read 2026-11-15).
KIND_CODES = {"By": "by", "Tettsted": "tettsted", "Tettbebyggelse": "tettbebyggelse", "Gard": "gard"}


def place(  # noqa: PLR0913 - one argument per field Kartverket gives
    name: str, kind: str, county: str, lat: float, lon: float, *, municipality: str = ""
) -> dict[str, object]:
    """One hit in Kartverket's /sted answer, in its own field names."""
    return {
        "stedsnavn": [{"skrivemåte": name, "navnestatus": "hovednavn"}],
        "navneobjekttype": kind,
        "representasjonspunkt": {"øst": lon, "nord": lat},
        "fylker": [{"fylkesnavn": county}],
        "kommuner": [{"kommunenavn": municipality or county.split(" - ", maxsplit=1)[0] + "vik"}],
    }


#: Made-up places. "Moen" is shared, as many real Norwegian names are. Some
#: counties have their name in two languages, as several real ones do.
PLACES: dict[str, list[dict[str, object]]] = {
    # A town and its municipality share a name and sit a little apart, as Bergen's do.
    "Testby": [
        place("Testby", "By", "Fjellfylke", 61.00412, 9.00377, municipality="Testby"),
        place("Testby", "Kommune", "Fjellfylke", 61.013, 9.012, municipality="Testby"),
    ],
    # Two towns of one name in one county, in different municipalities.
    "Bø": [
        place("Bø", "Tettsted", "Fjellfylke", 61.11, 9.11, municipality="Øvreli"),
        place("Bø", "Tettsted", "Fjellfylke", 61.12, 9.12, municipality="Nedreli"),
    ],
    "Moen": [
        place("Moen", "Tettsted", "Fjellfylke", 61.01, 9.01),
        place("Moen", "Tettsted", "Fjellfylke", 61.10, 9.10, municipality="Øvreli"),
        place("Moen", "Tettsted", "Kystfylke", 61.02, 9.02),
        place("Moen", "Gard", "Dalfylke", 61.03, 9.03),
        place("Moen", "Tettbebyggelse", "Nordfylke - Davvifylke", 61.06, 9.06),
    ],
    "Haugen": [
        place("Haugen", "Gard", "Fjellfylke", 61.04, 9.04),
        place("Haugen", "By", "Dalfylke", 61.05, 9.05),
    ],
    # More farms than fit on one page, ahead of the one town.
    "Lia": [place("Lia", "Gard", "Dalfylke", 61.07, 9.07)] * 30
    + [place("Lia", "By", "Kystfylke", 61.08, 9.08)],
    # A town whose own name says "i", as real ones do.
    "Strand i Dal": [place("Strand i Dal", "By", "Kystfylke", 61.09, 9.09)],
}


@dataclass
class FakeApi:
    """Answers as MET and Kartverket would, and counts what reached it."""

    clock: Clock = field(default_factory=Clock)
    body: dict[str, object] = field(default_factory=forecast)
    slow_down: bool = False
    #: What a 429 says in Retry-After, if anything: seconds, or an HTTP date.
    retry_after: str | None = None
    #: A status MET answers every forecast with, as when it is down.
    broken: int | None = None
    #: Fail inside the client with a message carrying the full URL, as a library bug might.
    crash: bool = False
    #: Refuse the connection, as when MET is unreachable; the error carries the request.
    refuse_connection: bool = False
    #: Seconds every answer takes, as when a service is slow.
    delay: float = 0
    expires_after_minutes: float = 30
    #: Send Expires with a "-0000" zone, which parses to a time with no zone.
    zoneless_expires: bool = False
    requests: list[httpx.Request] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle_async)

    async def _handle_async(self, request: httpx.Request) -> httpx.Response:
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.handle(request)

    def forecast_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == FORECAST_PATH]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == PLACES_PATH:
            return self._places(request)
        if request.url.path == FORECAST_PATH:
            return self._forecast(request)
        return httpx.Response(404)

    def _forecast(self, request: httpx.Request) -> httpx.Response:
        agent = request.headers.get("user-agent", "")
        if not agent.startswith("weather-mcp/") or " " not in agent:
            return httpx.Response(403, text="Missing or generic User-Agent")
        for key in ("lat", "lon"):
            value = request.url.params.get(key, "")
            if "." in value and len(value.split(".")[1]) > 4:
                return httpx.Response(403, text="Too many decimals")
        if self.refuse_connection:
            msg = f"connection refused asking {request.url}"
            raise httpx.ConnectError(msg, request=request)
        if self.crash:
            msg = f"unexpected failure asking {request.url}"
            raise RuntimeError(msg)
        if self.broken is not None:
            return httpx.Response(self.broken)
        if self.slow_down:
            return httpx.Response(429, headers={"Retry-After": self.retry_after} if self.retry_after else {})
        until = self.clock() + dt.timedelta(minutes=self.expires_after_minutes)
        if self.zoneless_expires:
            expires = email.utils.format_datetime(until.replace(tzinfo=None))
        else:
            expires = email.utils.format_datetime(until, usegmt=True)
        headers = {"Expires": expires, "Last-Modified": LAST_MODIFIED}
        if request.headers.get("if-modified-since") == LAST_MODIFIED:
            return httpx.Response(304, headers=headers)
        return httpx.Response(200, headers=headers, content=json.dumps(self.body).encode())

    def _places(self, request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("sok", "")
        hits = PLACES.get(name, [])
        kinds = request.url.params.get_list("navneobjekttype")
        if kinds:
            hits = [h for h in hits if KIND_CODES.get(str(h["navneobjekttype"])) in kinds]
        page = int(request.url.params.get("treffPerSide", "10"))
        body = {"metadata": {"totaltAntallTreff": len(hits)}, "navn": hits[:page]}
        return httpx.Response(200, content=json.dumps(body).encode())

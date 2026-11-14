"""A fake MET Norway and a fake Kartverket, behind httpx.MockTransport.

They copy the real limits the tests lean on (MET's terms, read 2026-11-14):
a 403 for a missing or generic User-Agent, a 403 for more than four decimals,
`Expires` and `Last-Modified` on every forecast, a 304 after a matching
`If-Modified-Since`, and a 429 when told to slow down.

Every place is made up, near 61.00 N 9.00 E.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
from dataclasses import dataclass, field

import httpx

START = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.UTC)
LAST_MODIFIED = "Sat, 14 Nov 2026 11:30:00 GMT"
FORECAST_PATH = "/weatherapi/locationforecast/2.0/compact"
PLACES_PATH = "/stedsnavn/v1/navn"


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


def place(name: str, kind: str, county: str, lat: float, lon: float) -> dict[str, object]:
    """One hit in Kartverket's /navn answer, in its own field names."""
    return {
        "skrivemåte": name,
        "navneobjekttype": kind,
        "representasjonspunkt": {"øst": lon, "nord": lat, "koordsys": 4258},
        "fylker": [{"fylkesnavn": county}],
        "kommuner": [{"kommunenavn": county + " kommune"}],
    }


#: Made-up places. "Moen" is shared, as many real Norwegian names are.
PLACES: dict[str, list[dict[str, object]]] = {
    "Testby": [place("Testby", "By", "Fjellfylke", 61.00412, 9.00377)],
    "Moen": [
        place("Moen", "Tettsted", "Fjellfylke", 61.01, 9.01),
        place("Moen", "Tettsted", "Kystfylke", 61.02, 9.02),
        place("Moen", "Gard", "Dalfylke", 61.03, 9.03),
    ],
    "Haugen": [
        place("Haugen", "Gard", "Fjellfylke", 61.04, 9.04),
        place("Haugen", "By", "Dalfylke", 61.05, 9.05),
    ],
}


@dataclass
class FakeApi:
    """Answers as MET and Kartverket would, and counts what reached it."""

    clock: Clock = field(default_factory=Clock)
    body: dict[str, object] = field(default_factory=forecast)
    slow_down: bool = False
    expires_after_minutes: float = 30
    requests: list[httpx.Request] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

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
        if self.slow_down:
            return httpx.Response(429)
        expires = email.utils.format_datetime(
            self.clock() + dt.timedelta(minutes=self.expires_after_minutes), usegmt=True
        )
        headers = {"Expires": expires, "Last-Modified": LAST_MODIFIED}
        if request.headers.get("if-modified-since") == LAST_MODIFIED:
            return httpx.Response(304, headers=headers)
        return httpx.Response(200, headers=headers, content=json.dumps(self.body).encode())

    def _places(self, request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("sok", "")
        hits = PLACES.get(name, [])
        body = {"metadata": {"totaltAntallTreff": len(hits)}, "navn": hits}
        return httpx.Response(200, content=json.dumps(body).encode())

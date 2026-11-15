"""A made-up MET and Kartverket, for trying the tools by voice with no network.

Every answer of a simulated server starts "Simulated:", and the places and the weather
are invented: one made-up home, Testheim, at 61.00 N 9.00 E.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx

from weather_mcp.cache import CachedClient
from weather_mcp.config import Config, Place
from weather_mcp.places import PlaceFinder
from weather_mcp.server import build_server
from weather_mcp.weather import Weather

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mcp.server.mcpserver import MCPServer

HOME = Place(name="Testheim", lat=61.0, lon=9.0)
CONFIG = Config(contact="https://example.org/weather-mcp-simulated", home=HOME)
AGENT = "weather-mcp/simulated https://example.org/weather-mcp-simulated"
#: The made-up places a simulated run can find, as Kartverket names them.
PLACES = {"Testheim": HOME}
#: The sky by Oslo hour of the day: cloudy mornings, light rain after noon, clear evenings.
SKY = ((6, "fair_night"), (12, "cloudy"), (17, "lightrain"), (23, "clearsky_night"), (24, "fair_night"))


def _sky(hour: int) -> str:
    return next(code for until, code in SKY if hour < until)


def _forecast(now: dt.datetime) -> dict[str, Any]:
    """Sixty made-up hours from the hour that is now, in MET's compact shape."""
    start = now.replace(minute=0, second=0, microsecond=0)
    series = []
    for n in range(60):
        time = start + dt.timedelta(hours=n)
        local_hour = (time.hour + 1) % 24
        symbol = _sky(local_hour)
        series.append(
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "instant": {
                        "details": {
                            "air_temperature": round(
                                4 + 3 * math.sin((local_hour - 8) / 24 * 2 * math.pi), 1
                            ),
                            "wind_speed": 3.0 + local_hour % 4,
                        }
                    },
                    "next_1_hours": {
                        "summary": {"symbol_code": symbol},
                        "details": {"precipitation_amount": 0.4 if "rain" in symbol else 0.0},
                    },
                },
            }
        )
    return {"type": "Feature", "properties": {"meta": {}, "timeseries": series}}


def _place(name: str, place: Place) -> dict[str, Any]:
    return {
        "stedsnavn": [{"skrivemåte": name, "navnestatus": "hovednavn"}],
        "navneobjekttype": "By",
        "representasjonspunkt": {"øst": place.lon, "nord": place.lat},
        "fylker": [{"fylkesnavn": "Prøvefylke"}],
        "kommuner": [{"kommunenavn": "Prøvevik"}],
    }


def _answer(request: httpx.Request) -> httpx.Response:
    """MET's forecast or Kartverket's places, made up, for any request; nothing leaves."""
    if request.url.path.endswith("/locationforecast/2.0/compact"):
        now = dt.datetime.now(dt.UTC)
        expires = now + dt.timedelta(minutes=30)
        headers = {"Expires": expires.strftime("%a, %d %b %Y %H:%M:%S GMT")}
        return httpx.Response(200, headers=headers, content=json.dumps(_forecast(now)).encode())
    if request.url.path.endswith("/stedsnavn/v1/sted"):
        name = request.url.params.get("sok", "")
        hits = [_place(n, p) for n, p in PLACES.items() if n.lower() == name.lower()]
        body = {"metadata": {"totaltAntallTreff": len(hits)}, "navn": hits}
        return httpx.Response(200, content=json.dumps(body).encode())
    return httpx.Response(404)


@asynccontextmanager
async def simulated_server() -> AsyncIterator[MCPServer[Any]]:
    """The weather server on made-up services, with no cache file and no network."""
    # RULE: a simulated run never touches the network
    async with httpx.AsyncClient(transport=httpx.MockTransport(_answer)) as http:
        weather = Weather(CONFIG, CachedClient(http, AGENT), PlaceFinder(http, AGENT))
        yield build_server(weather, simulated=True)

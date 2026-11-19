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
#: How many entries are an hour apart, and how far the made-up forecast reaches, as MET's does.
HOURLY = 60
REACH = dt.timedelta(days=9, hours=12)


def _sky(hour: int) -> str:
    return next(code for until, code in SKY if hour < until)


def _forecast(now: dt.datetime) -> dict[str, Any]:
    """Made-up weather in MET's shape: sixty hours, then six-hour blocks for nine days more.

    As in MET's own answer, the hours carry next_1_hours, the blocks at 00, 06, 12 and 18 UTC
    carry next_6_hours only, and the last entry carries neither.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    times = [start + dt.timedelta(hours=n) for n in range(HOURLY)]
    while times[-1] < start + REACH:
        times.append(times[-1] + dt.timedelta(hours=6 if times[-1].hour % 6 == 0 else 1))
    series = [_entry(time, hourly=n < HOURLY, last=n == len(times) - 1) for n, time in enumerate(times)]
    return {"type": "Feature", "properties": {"meta": {}, "timeseries": series}}


def _hourly(local_hour: int, wind: float) -> dict[str, float]:
    """The details MET's complete answer gives only for its hours: fog, UV and gusts."""
    return {
        "fog_area_fraction": 30.0 if local_hour < 8 else 0.0,  # noqa: PLR2004 - misty mornings
        "ultraviolet_index_clear_sky": 1.0 if 10 <= local_hour < 15 else 0.0,  # noqa: PLR2004 - midday sun
        "wind_speed_of_gust": wind * 2,
    }


def _entry(time: dt.datetime, *, hourly: bool, last: bool) -> dict[str, Any]:
    """One entry of the made-up forecast, its block an hour or six hours long, or none at the end."""
    local_hour = (time.hour + 1) % 24
    symbol = _sky(local_hour)
    hours = 1 if hourly else 6
    temperature = round(4 + 3 * math.sin((local_hour - 8) / 24 * 2 * math.pi), 1)
    details: dict[str, float] = {
        "air_temperature": temperature,
        "wind_speed": 3.0 + local_hour % 4,
        "wind_from_direction": 200.0,
        "relative_humidity": 85.0 - 2 * local_hour % 20,
        "dew_point_temperature": round(temperature - 3, 1),
    }
    if hourly:
        details |= _hourly(local_hour, details["wind_speed"])
    data: dict[str, Any] = {"instant": {"details": details}}
    if not last:
        data[f"next_{hours}_hours"] = {
            "summary": {"symbol_code": symbol},
            "details": {"precipitation_amount": 0.4 * hours if "rain" in symbol else 0.0},
        }
    return {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data}


def _sky_answer(params: httpx.QueryParams) -> dict[str, Any]:
    """A made-up sunrise 3.0 answer for the day asked: the sun up 08:30 to 15:30, the moon by date."""
    date, offset = params.get("date", "2026-01-01"), params.get("offset", "+01:00")
    day = dt.date.fromisoformat(date)
    return {
        "properties": {
            "sunrise": {"time": f"{date}T08:30{offset}"},
            "sunset": {"time": f"{date}T15:30{offset}"},
            "solarmidnight": {"visible": False},
            "moonrise": {"time": f"{date}T14:00{offset}"},
            "moonset": {"time": f"{date}T01:00{offset}"},
            "moonphase": day.toordinal() * 12.2 % 360,  # about a lunar month of 29.5 days
        }
    }


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
    # The made-up forecast carries the complete answer's details, so it serves both.
    if request.url.path.endswith(("/locationforecast/2.0/compact", "/locationforecast/2.0/complete")):
        now = dt.datetime.now(dt.UTC)
        expires = now + dt.timedelta(minutes=30)
        headers = {"Expires": expires.strftime("%a, %d %b %Y %H:%M:%S GMT")}
        return httpx.Response(200, headers=headers, content=json.dumps(_forecast(now)).encode())
    if "/sunrise/3.0/" in request.url.path:
        return httpx.Response(200, content=json.dumps(_sky_answer(request.url.params)).encode())
    if request.url.path.endswith("/stedsnavn/v1/sted"):
        return httpx.Response(200, content=json.dumps(_places(request.url.params.get("sok", ""))).encode())
    return httpx.Response(404)


def _places(name: str) -> dict[str, Any]:
    """Kartverket's answer for a name, from the made-up places."""
    hits = [_place(n, p) for n, p in PLACES.items() if n.lower() == name.lower()]
    return {"metadata": {"totaltAntallTreff": len(hits)}, "navn": hits}


@asynccontextmanager
async def simulated_server() -> AsyncIterator[MCPServer[Any]]:
    """The weather server on made-up services, with no cache file and no network."""
    # RULE: a simulated run never touches the network
    async with httpx.AsyncClient(transport=httpx.MockTransport(_answer)) as http:
        weather = Weather(CONFIG, CachedClient(http, AGENT), PlaceFinder(http, AGENT))
        yield build_server(weather, simulated=True)

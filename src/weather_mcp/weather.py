"""What the weather is now, as one short sentence for a voice.

The forecast is MET Norway's locationforecast compact. Times are spoken in Oslo
time, never in UTC.
"""

from __future__ import annotations

import zoneinfo
from typing import TYPE_CHECKING, Any

import httpx

from weather_mcp.cache import RefusedError, SlowedDownError, UpstreamError
from weather_mcp.config import config_path

if TYPE_CHECKING:
    from weather_mcp.cache import Answer, CachedClient
    from weather_mcp.config import Config, Place
    from weather_mcp.places import PlaceFinder

FORECAST = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
DOWN = "MET isn't answering. Yr's app still works."
HELD_OFF = "MET asked us to slow down. Ask again in a few minutes."

#: MET's symbol codes, without their _day, _night or _polartwilight ending.
SKY = {
    "clearsky": "clear",
    "fair": "fair",
    "partlycloudy": "partly cloudy",
    "cloudy": "cloudy",
    "fog": "foggy",
    "lightrain": "light rain",
    "rain": "rain",
    "heavyrain": "heavy rain",
    "lightrainshowers": "light rain showers",
    "rainshowers": "rain showers",
    "heavyrainshowers": "heavy rain showers",
    "lightsleet": "light sleet",
    "sleet": "sleet",
    "heavysleet": "heavy sleet",
    "lightsnow": "light snow",
    "snow": "snow",
    "heavysnow": "heavy snow",
    "lightsnowshowers": "light snow showers",
    "snowshowers": "snow showers",
    "rainandthunder": "rain and thunder",
}


def _degrees(value: float) -> str:
    whole = round(value)
    unit = "degree" if abs(whole) == 1 else "degrees"
    return f"Minus {-whole} {unit}" if whole < 0 else f"{whole} {unit}"


def _sky(now: dict[str, Any]) -> str:
    code = str(now["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", ""))
    return SKY.get(code.split("_", maxsplit=1)[0], "")


def _sentence(answer: Answer, place: Place) -> str:
    now = answer.data["properties"]["timeseries"][0]
    temperature = _degrees(float(now["data"]["instant"]["details"]["air_temperature"]))
    sky = _sky(now)
    say = f"{temperature} and {sky} in {place.name}." if sky else f"{temperature} in {place.name}."
    # RULE: a slowed answer says how old it is
    if answer.slowed:
        say += f" The forecast is from {answer.fetched.astimezone(OSLO):%H:%M}; MET asked us to slow down."
    return say


class Weather:
    """The tools' work, apart from the server that carries them."""

    def __init__(self, config: Config, cache: CachedClient, places: PlaceFinder) -> None:
        """Answer from config's home, or from a name the finder can place."""
        self._config, self._cache, self._places = config, cache, places

    async def now(self, place: str | None = None) -> dict[str, Any]:
        """The weather right now, at home or at a named place in Norway."""
        where = await self._where(place)
        if isinstance(where, str):
            return {"success": False, "say": where}
        params = {"lat": f"{where.lat:.2f}", "lon": f"{where.lon:.2f}"}
        try:
            answer = await self._cache.get_json(FORECAST, params)
        except SlowedDownError:
            return {"success": False, "say": HELD_OFF}
        except RefusedError:
            return {
                "success": False,
                "say": f"MET refused the request. Check the contact in {config_path()}.",
            }
        except (UpstreamError, httpx.HTTPError):
            return {"success": False, "say": DOWN}
        return {"success": True, "say": _sentence(answer, where), "place": where.name}

    async def _where(self, place: str | None) -> Place | str:
        """The place to ask about, or the sentence saying why there is none."""
        if not place:
            if self._config.home is None:
                return f"Home isn't set yet. Add a [home] to {config_path()}."
            return self._config.home
        try:
            found = await self._places.find(place)
        except httpx.HTTPError:
            return "Kartverket isn't answering, so I can't find that place. Try again later."
        if found.place is not None:
            return found.place
        if found.choices:
            # Only a name looked up whole can be shared: one with a county names one county.
            *rest, last = found.choices
            counties = f"{', '.join(rest)} or {last}" if rest else last
            return f"Which {place.strip()}: in {counties}?"
        return f"I only know places in Norway so far, and I can't find {place}. Yr's app has the rest."

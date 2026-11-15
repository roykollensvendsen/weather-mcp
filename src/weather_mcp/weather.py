"""What the weather is now, as one short sentence for a voice.

The forecast is MET Norway's locationforecast compact. Times are spoken in Oslo
time, never in UTC.
"""

from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from weather_mcp.cache import RefusedError, SlowedDownError, UpstreamError
from weather_mcp.config import Place, config_path

if TYPE_CHECKING:
    from weather_mcp.cache import Answer, CachedClient
    from weather_mcp.config import Config
    from weather_mcp.places import PlaceFinder

FORECAST = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
DOWN = "MET isn't answering. Yr's app still works."
HELD_OFF = "MET asked us to slow down. Ask again in a few minutes."

#: Symbols with words of their own. The rest are built from parts, below.
PLAIN = {
    "clearsky": "clear",
    "fair": "fair",
    "partlycloudy": "partly cloudy",
    "cloudy": "cloudy",
    "fog": "foggy",
}
#: How MET builds every other symbol: strength, then what falls, then the rest.
#: MET's own list spells two of them "lightssleet…" and "lightssnow…".
SYMBOL = re.compile(
    r"^(?:(?P<strength>light|lights|heavy))?(?P<falls>rain|sleet|snow)(?P<showers>showers)?(?P<thunder>andthunder)?$"
)


def sky_words(code: str) -> str:
    """The spoken words for a MET symbol code, or "" for one not known."""
    code = code.split("_", maxsplit=1)[0]
    if code in PLAIN:
        return PLAIN[code]
    parts = SYMBOL.match(code)
    if parts is None:
        return ""
    strength = {"light": "light ", "lights": "light ", "heavy": "heavy "}.get(parts["strength"] or "", "")
    showers = " showers" if parts["showers"] else ""
    thunder = " and thunder" if parts["thunder"] else ""
    return f"{strength}{parts['falls']}{showers}{thunder}"


def _degrees(value: float) -> str:
    whole = round(value)
    unit = "degree" if abs(whole) == 1 else "degrees"
    return f"Minus {-whole} {unit}" if whole < 0 else f"{whole} {unit}"


def _sky(now: dict[str, Any]) -> str:
    code = str(now["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", ""))
    return sky_words(code)


#: A phone position less exact than this, in metres, is said to be rough.
ROUGH_M = 10_000.0
#: What a phone's position is called in an answer.
HERE = "where you are"


#: What the voice hears when a position came but cannot be used.
UNUSABLE = "I can't use the phone's position, so ask again with a place name."


class Here(Place):
    """The phone's position: said as where you are, and kept in memory only."""


def _spoken(where: Place) -> str:
    return HERE if isinstance(where, Here) else f"in {where.name}"


def _rough(where: Place, accuracy_m: float | None) -> str:
    if isinstance(where, Here) and accuracy_m is not None and accuracy_m > ROUGH_M:
        return " The phone's position is rough, so this may be off."
    return ""


def _position(lat: float | None, lon: float | None) -> Place | str | None:
    """The phone's position; a sentence when it can't be used; None without one."""
    if lat is None and lon is None:
        return None
    # Half a position, taken for home, would answer "here" for the wrong place.
    if lat is None or lon is None:
        return UNUSABLE
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):  # noqa: PLR2004 - the ends of the earth
        return UNUSABLE
    # Rounded once, by point(), for MET and the cache alike.
    return Here(name=HERE, lat=lat, lon=lon)


def _sentence(answer: Answer, where: str) -> str:
    now = answer.data["properties"]["timeseries"][0]
    temperature = _degrees(float(now["data"]["instant"]["details"]["air_temperature"]))
    sky = _sky(now)
    say = f"{temperature} and {sky} {where}." if sky else f"{temperature} {where}."
    # RULE: a slowed answer says how old it is
    if answer.slowed:
        say += f" The forecast is from {answer.fetched.astimezone(OSLO):%H:%M}; MET asked us to slow down."
    return say


#: The days a forecast can be asked for, by how many days ahead they are.
DAYS = {"today": 0, "tomorrow": 1}
#: The parts of a day said, by the Oslo hour each begins and ends. The hours before 06:00
#: and the 23:00 hour belong to no part, though they still count toward the range, rain and wind.
PARTS = (("in the morning", 6, 12), ("at midday", 12, 17), ("in the evening", 17, 23))
#: What "today" hears once MET's first hour is already tomorrow's: the day is over, not early.
NEARLY_OVER = "Today is nearly over. Ask for tomorrow instead."


@dataclass(frozen=True)
class Hour:
    """One hour of MET's forecast, by Oslo time, with what this plugin says of it."""

    at: dt.datetime
    temperature: float
    wind: float
    rain: float
    symbol: str


def _hours_on(series: list[dict[str, Any]], date: dt.date, *, after: dt.datetime) -> list[Hour]:
    """The hours MET gives for `date` in Oslo, from the hour that is now on."""
    hours = []
    for entry in series:
        at = dt.datetime.fromisoformat(entry["time"]).astimezone(OSLO)
        # RULE: a forecast holds only its own day
        if at.date() != date:
            continue
        # RULE: today leaves out what has passed
        if at < after.replace(minute=0, second=0, microsecond=0):
            continue
        data = entry["data"]
        # Today and tomorrow are hourly in MET's answer. Further ahead an hour may carry only
        # next_6_hours, whose rain is six hours' worth, so a tool reaching there must not sum it.
        later = data.get("next_1_hours") or data.get("next_6_hours") or {}
        details = data["instant"]["details"]
        hours.append(
            Hour(
                at=at,
                temperature=float(details["air_temperature"]),
                wind=float(details.get("wind_speed", 0.0)),
                rain=float(later.get("details", {}).get("precipitation_amount", 0.0)),
                symbol=str(later.get("summary", {}).get("symbol_code", "")),
            )
        )
    return hours


def _span(low: float, high: float) -> str:
    def said(value: int) -> str:
        return f"minus {-value}" if value < 0 else str(value)

    low_, high_ = round(low), round(high)
    if low_ == high_:
        return f"{said(low_)} degree" if abs(low_) == 1 else f"{said(low_)} degrees"
    return f"{said(low_)} to {said(high_)} degrees"


def _falls(hours: list[Hour]) -> str:
    """What comes down, in a word: rain, sleet, snow, or rain and snow when mixed."""
    kinds = {m["falls"] for h in hours if (m := SYMBOL.match(h.symbol.split("_")[0])) is not None}
    return kinds.pop() if len(kinds) == 1 else "rain and snow" if kinds else "rain"


def _amount(hours: list[Hour]) -> str:
    total, falls = sum(h.rain for h in hours), _falls(hours)
    if total == 0:
        return f"no {falls}"
    whole = round(total)
    if whole == 0:
        return f"a little {falls}"
    return f"{whole} {'millimetre' if whole == 1 else 'millimetres'} of {falls}"


def _main_sky(hours: list[Hour], start: int, end: int) -> str:
    """The sky said most often between two Oslo hours, or "" when none is known."""
    skies = [said for h in hours if start <= h.at.hour < end and (said := sky_words(h.symbol))]
    return max(skies, key=skies.count) if skies else ""


def _parts(hours: list[Hour]) -> str:
    """The main sky in each part of the day still to come, or one sky for all of it."""
    said = [(name, sky) for name, start, end in PARTS if (sky := _main_sky(hours, start, end))]
    skies = {sky for _, sky in said}
    if len(said) == len(PARTS) and len(skies) == 1:
        return f"{skies.pop()} all day"
    return _listed([f"{sky} {name}" for name, sky in said])


def _listed(words: list[str]) -> str:
    """Words said as a list: "a", "a and b", "a, b and c"."""
    return " and ".join([", ".join(words[:-1]), words[-1]]) if len(words) > 1 else "".join(words)


def _day_sentence(hours: list[Hour]) -> str:
    temperatures = [h.temperature for h in hours]
    wind = round(max(h.wind for h in hours))
    unit = "metre" if wind == 1 else "metres"
    span = _span(min(temperatures), max(temperatures))
    say = f"{span}, {_amount(hours)} and wind up to {wind} {unit} a second"
    parts = _parts(hours)
    return f"{say}; {parts}." if parts else f"{say}."


#: The longest place name said back, in letters. Names longer than this are cut, not refused.
ECHO = 40


def _echo(place: str) -> str:
    """A spoken place said back as one short line, whatever arrived."""
    words = " ".join(place.split())
    return words if len(words) <= ECHO else words[:ECHO].rstrip() + "…"


def point(place: Place) -> dict[str, str]:
    """The point MET is asked about, exactly as the request and the cache spell it."""
    # RULE: a position is rounded to two decimals before it is used
    return {"lat": f"{place.lat:.2f}", "lon": f"{place.lon:.2f}"}


class Weather:
    """The tools' work, apart from the server that carries them."""

    def __init__(self, config: Config, cache: CachedClient, places: PlaceFinder) -> None:
        """Answer from config's home, or from a name the finder can place."""
        self._config, self._cache, self._places = config, cache, places

    async def now(
        self,
        place: str | None = None,
        *,
        lat: float | None = None,
        lon: float | None = None,
        accuracy_m: float | None = None,
    ) -> dict[str, Any]:
        """The weather right now: at a named place, else at the phone's position, else at home."""
        where = await self._resolve(place, lat, lon)
        if isinstance(where, str):
            return {"success": False, "say": where}
        answer = await self._fetch(where)
        if isinstance(answer, str):
            return {"success": False, "say": answer}
        say = _sentence(answer, _spoken(where)) + _rough(where, accuracy_m)
        return {"success": True, "say": say, "place": where.name}

    async def forecast(
        self,
        day: str = "tomorrow",
        place: str | None = None,
        *,
        lat: float | None = None,
        lon: float | None = None,
        accuracy_m: float | None = None,
    ) -> dict[str, Any]:
        """Today or tomorrow in one sentence: the range, rain, wind and the day in three parts."""
        where = await self._resolve(place, lat, lon)
        if isinstance(where, str):
            return {"success": False, "say": where}
        answer = await self._fetch(where)
        if isinstance(answer, str):
            return {"success": False, "say": answer}
        today = self._cache.now().astimezone(OSLO)
        date = today.date() + dt.timedelta(days=DAYS[day])
        hours = _hours_on(answer.data["properties"]["timeseries"], date, after=today)
        if not hours:
            return {
                "success": False,
                "say": NEARLY_OVER if date == today.date() else f"MET has no forecast for {day} yet.",
            }
        say = f"{day.capitalize()} {_spoken(where)}: {_day_sentence(hours)}" + _rough(where, accuracy_m)
        return {"success": True, "say": say, "place": where.name}

    async def _resolve(self, place: str | None, lat: float | None, lon: float | None) -> Place | str:
        """A named place, else the phone's position, else home; or the sentence saying why not."""
        if place:
            return await self._where(place)
        here = _position(lat, lon)
        return here if here is not None else await self._where(None)

    async def _fetch(self, where: Place) -> Answer | str:
        """MET's forecast for the point, or the sentence saying why there is none."""
        try:
            # A position is the phone's own, so it is kept in memory only, never in the file.
            return await self._cache.get_json(FORECAST, point(where), on_disk=not isinstance(where, Here))
        except SlowedDownError:
            return HELD_OFF
        except RefusedError:
            return f"MET refused the request. Check the contact in {config_path()}."
        except (UpstreamError, httpx.HTTPError):
            return DOWN

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
            return f"Which {_echo(place)}: in {counties}?"
        return f"I only know places in Norway so far, and I can't find {_echo(place)}. Yr's app has the rest."

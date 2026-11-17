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
from weather_mcp.days import label, which_day

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
#: The parts of a day said, by the Oslo hour each begins and ends. The hours before 06:00
#: and the 23:00 hour belong to no part, though they still count toward the range, rain and wind.
PARTS = (("in the morning", 6, 12), ("at midday", 12, 17), ("in the evening", 17, 23))
#: What "today" hears once MET's first hour is already tomorrow's: the day is over, not early.
NEARLY_OVER = "Today is nearly over. Ask for tomorrow instead."
#: What a word that names no day hears: a question back, never a guess.
WHICH = "Which day? Say today, tomorrow, a weekday or a date such as 20.11."
PASSED = "That day has passed. Ask for today or a day to come."
#: The Oslo hour the evening begins: a day is whole once MET's forecast reaches it.
EVENING = PARTS[-1][1]
#: How many days the week gives, from tomorrow, when no last day is asked.
WEEK_DAYS = 5
#: The wind, in metres a second, from which a week line says it.
WINDY = 10
#: How far apart, in degrees, two days' lows and highs may be and still be said together.
ALIKE = 2
#: A day with less rain or snow than this, in millimetres, is said as dry.
DRY = 1.0
SOONER = "For today alone, ask for today's forecast."
NO_WEEK = "MET has no forecast for the coming days yet."


@dataclass(frozen=True)
class Hour:
    """One hour of MET's forecast, by Oslo time, with what this plugin says of it."""

    at: dt.datetime
    temperature: float
    wind: float
    rain: float
    symbol: str
    #: Whether the hour comes from a six-hour block, as MET gives beyond the first days.
    coarse: bool = False


def _block(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """The stretch an entry's sky and rain are for, and how many hours it covers; none at the end."""
    for key, length in (("next_1_hours", 1), ("next_6_hours", 6)):
        if key in data:
            return data[key], length
    return {}, 0


def _counted_rain(series: list[dict[str, Any]]) -> list[float]:
    """Each entry's rain, with none counted twice where its stretch overlaps one already counted.

    MET's hours carry next_1_hours; further ahead an entry carries only next_6_hours, which holds
    six hours' worth. Should an hour that gives only its block be followed by hours of their own,
    their rain is already in the block. The rain falls on the day its stretch begins.
    """
    counted: dt.datetime | None = None
    rains = []
    for entry in series:
        at = dt.datetime.fromisoformat(entry["time"])
        later, length = _block(entry["data"])
        rain = float(later.get("details", {}).get("precipitation_amount", 0.0))
        # RULE: rain is counted once for each stretch of time
        rains.append(rain if counted is None or at >= counted else 0.0)
        if length:
            counted = max(counted or at, at + dt.timedelta(hours=length))
    return rains


def _hours_on(series: list[dict[str, Any]], date: dt.date, *, after: dt.datetime) -> list[Hour]:
    """The hours MET gives for `date` in Oslo, from the hour that is now on."""
    hours = []
    for entry, rain in zip(series, _counted_rain(series), strict=True):
        at = dt.datetime.fromisoformat(entry["time"]).astimezone(OSLO)
        # RULE: a forecast holds only its own day
        if at.date() != date:
            continue
        # RULE: today leaves out what has passed
        if at < after.replace(minute=0, second=0, microsecond=0):
            continue
        later, length = _block(entry["data"])
        details = entry["data"]["instant"]["details"]
        hours.append(
            Hour(
                at=at,
                temperature=float(details["air_temperature"]),
                wind=float(details.get("wind_speed", 0.0)),
                rain=rain,
                symbol=str(later.get("summary", {}).get("symbol_code", "")),
                coarse=length > 1,
            )
        )
    return hours


def _last_whole_day(series: list[dict[str, Any]]) -> dt.date | None:
    """The last day MET's forecast reaches into the evening of, by Oslo time."""
    last = None
    for entry in series:
        at = dt.datetime.fromisoformat(entry["time"]).astimezone(OSLO)
        if _block(entry["data"])[1] and at.hour >= EVENING:
            last = at.date()
    return last


def _within_a_sentence(date: dt.date, today: dt.date) -> str:
    """How `date` is said inside a sentence: "tomorrow" lower-case, a weekday as a name."""
    name = label(date, today)
    return name.lower() if name == "Tomorrow" else name


def _missing(date: dt.date, now: dt.datetime, hours: list[Hour], series: list[dict[str, Any]]) -> str:
    """Why MET has no forecast to give for `date`, or "" when it has one."""
    if date == now.date():
        return "" if hours else NEARLY_OVER
    last = _last_whole_day(series)
    if last is not None and date <= last:
        return ""
    if last is None or last <= now.date():
        return f"MET has no forecast for {_within_a_sentence(date, now.date())} yet."
    # RULE: a day past the forecast says how far it reaches
    return f"MET's forecast reaches to {label(last, now.date())}."


def _range(low: float, high: float, *, coarse: bool) -> str:
    """The range as said, "about" first when it comes from six-hour blocks, whose few readings miss peaks."""
    span = _span(low, high)
    # RULE: a day in six-hour blocks says about for its range
    return f"about {span}" if coarse else span


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
    span = _range(min(temperatures), max(temperatures), coarse=any(h.coarse for h in hours))
    say = f"{span}, {_amount(hours)} and wind up to {wind} {unit} a second"
    parts = _parts(hours)
    return f"{say}; {parts}." if parts else f"{say}."


@dataclass(frozen=True)
class Day:
    """One day of the coming days, as its line in the week says it."""

    date: dt.date
    low: float
    high: float
    rain: float
    #: "dry", or what comes down: rain, sleet, snow, or rain and snow.
    falls: str
    wind: float
    coarse: bool


def _day(date: dt.date, hours: list[Hour]) -> Day:
    temperatures = [h.temperature for h in hours]
    rain = sum(h.rain for h in hours)
    return Day(
        date=date,
        low=min(temperatures),
        high=max(temperatures),
        rain=rain,
        falls="dry" if rain < DRY else _falls(hours),
        wind=max(h.wind for h in hours),
        coarse=any(h.coarse for h in hours),
    )


def _alike(one: Day, other: Day) -> bool:
    """Whether two days sound alike: the same rain or dry, strong wind on both or neither, near ranges."""
    return (
        one.falls == other.falls
        and (one.wind >= WINDY) == (other.wind >= WINDY)
        and abs(one.low - other.low) <= ALIKE
        and abs(one.high - other.high) <= ALIKE
    )


def _groups(days: list[Day]) -> list[list[Day]]:
    """The days in runs that sound alike, each run said as one line."""
    groups: list[list[Day]] = []
    for day in days:
        if groups and _alike(groups[-1][0], day):
            # RULE: days that sound alike are said together
            groups[-1].append(day)
        else:
            groups.append([day])
    return groups


def _names(group: list[Day], today: dt.date) -> str:
    """A run's days as said: "Friday", "Friday and Saturday", "Friday to Sunday"."""
    first, last = label(group[0].date, today), label(group[-1].date, today)
    if len(group) == 1:
        return first
    return f"{first} and {last}" if len(group) == 2 else f"{first} to {last}"  # noqa: PLR2004 - two days


def _line(group: list[Day], today: dt.date) -> str:
    """One run of alike days: its names, range, rain or dry, and the wind when it is strong."""
    span = _range(min(d.low for d in group), max(d.high for d in group), coarse=any(d.coarse for d in group))
    wind = round(max(d.wind for d in group))
    # RULE: a week line says the wind only when it is strong
    windy = f", wind up to {wind}" if wind >= WINDY else ""
    return f"{_names(group, today)}: {span}, {group[0].falls}{windy}."


def _wettest(days: list[Day], today: dt.date) -> str:
    """The week's last sentence: its wettest and its driest day, or that every day is dry."""
    wettest, driest = max(days, key=lambda d: d.rain), min(days, key=lambda d: d.rain)
    if wettest.rain < DRY:
        return "Dry every day."
    whole = round(wettest.rain)
    amount = f"{whole} {'millimetre' if whole == 1 else 'millimetres'}"
    wet, dry = _within_a_sentence(wettest.date, today), _within_a_sentence(driest.date, today)
    # RULE: the week ends with its wettest and driest day
    return f"Wettest is {wet}, with {amount}; driest is {dry}."


def _week_refusal(end: dt.date | None, today: dt.date) -> str:
    """Why a week up to `end` cannot be given, or "" when it can."""
    if end is None:
        return WHICH
    if end < today:
        return PASSED
    return SOONER if end == today else ""


def _week_end(until: str | None, today: dt.date) -> dt.date | None:
    """The last of the coming days: the one asked for, else five days from today."""
    return today + dt.timedelta(days=WEEK_DAYS) if until is None else which_day(until, today)


def _coming_days(series: list[dict[str, Any]], now: dt.datetime, end: dt.date) -> tuple[str, str] | None:
    """How the coming days to `end` begin and their lines, or None when MET covers none of them."""
    today = now.date()
    last = _last_whole_day(series)
    if last is None or last <= today:
        return None
    # RULE: the week stops where the forecast does
    end = min(end, last)
    days = [_day(d, _hours_on(series, d, after=now)) for d in _dates(today, end)]
    lines = " ".join(_line(group, today) for group in _groups(days))
    said = f"The next {len(days)} days" if len(days) > 1 else "The next day"
    return said, f"{lines} {_wettest(days, today)}"


def _dates(today: dt.date, end: dt.date) -> list[dt.date]:
    """The days from tomorrow to `end`, both counted."""
    return [today + dt.timedelta(days=n) for n in range(1, (end - today).days + 1)]


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
        found = await self._look_up(place, lat, lon)
        if isinstance(found, dict):
            return found
        where, answer = found
        say = _sentence(answer, _spoken(where)) + _rough(where, accuracy_m)
        return {"success": True, "say": say, "place": where.name}

    async def forecast(
        self,
        place: str | None = None,
        *,
        day: str = "tomorrow",
        lat: float | None = None,
        lon: float | None = None,
        accuracy_m: float | None = None,
    ) -> dict[str, Any]:
        """Any day MET covers, in one sentence: the range, rain, wind and the day in three parts."""
        now = self._cache.now().astimezone(OSLO)
        date = which_day(day, now.date())
        if date is None:
            # RULE: an unknown day is asked about not guessed
            return {"success": False, "say": WHICH}
        if date < now.date():
            # RULE: a day already gone is refused
            return {"success": False, "say": PASSED}
        found = await self._look_up(place, lat, lon)
        if isinstance(found, dict):
            return found
        where, answer = found
        series = answer.data["properties"]["timeseries"]
        hours = _hours_on(series, date, after=now)
        missing = _missing(date, now, hours, series)
        if missing:
            return {"success": False, "say": missing}
        say = f"{label(date, now.date())} {_spoken(where)}: {_day_sentence(hours)}" + _rough(
            where, accuracy_m
        )
        return {"success": True, "say": say, "place": where.name}

    async def week(
        self,
        place: str | None = None,
        *,
        until: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        accuracy_m: float | None = None,
    ) -> dict[str, Any]:
        """The coming days from tomorrow, a short line each: five days, or up to `until`."""
        now = self._cache.now().astimezone(OSLO)
        end = _week_end(until, now.date())
        refused = _week_refusal(end, now.date())
        if refused or end is None:
            return {"success": False, "say": refused}
        found = await self._look_up(place, lat, lon)
        if isinstance(found, dict):
            return found
        where, answer = found
        coming = _coming_days(answer.data["properties"]["timeseries"], now, end)
        if coming is None:
            return {"success": False, "say": NO_WEEK}
        said, lines = coming
        say = f"{said} {_spoken(where)}: {lines}" + _rough(where, accuracy_m)
        return {"success": True, "say": say, "place": where.name}

    async def _look_up(
        self, place: str | None, lat: float | None, lon: float | None
    ) -> tuple[Place, Answer] | dict[str, Any]:
        """The place asked about and MET's answer for it, or the refusal to say instead."""
        where = await self._resolve(place, lat, lon)
        if isinstance(where, str):
            return {"success": False, "say": where}
        answer = await self._fetch(where)
        if isinstance(answer, str):
            return {"success": False, "say": answer}
        return where, answer

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

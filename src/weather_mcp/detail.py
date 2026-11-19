"""One detail of MET's complete forecast, said as its value and nothing more.

The details are those Yr's app shows beyond the basics: the UV index, humidity, dew point,
fog and the wind with its gusts and direction. The sun and the moon are words here too,
but their answers come from MET's sunrise service, in sky. Each answer is one value for one time, or
for a stretch of time said briefly: a range, a peak or the strongest hour.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

COMPLETE = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
#: The details asked for, by the word the voice sends, and the words also taken for them.
WORDS = {
    "uv": ("uv", "uv index", "uv_index"),
    "humidity": ("humidity", "relative humidity"),
    "dew_point": ("dew point", "dew_point", "dewpoint"),
    "fog": ("fog", "visibility"),
    "wind": ("wind", "gusts", "gust", "wind direction"),
    "sunrise": ("sunrise", "sun rise", "sun up"),
    "sunset": ("sunset", "sun set", "sundown"),
    "sun": ("sun", "daylight"),
    "moon": ("moon", "moon phase", "moonphase"),
    "moonrise": ("moonrise", "moon rise"),
    "moonset": ("moonset", "moon set"),
}
WHICH_DETAIL = (
    "Which detail? Say uv, humidity, dew point, fog, wind, sunrise, sunset, sun, moon, moonrise or moonset."
)
#: MET's own field for each detail, as its complete forecast names it (read 2026-11-19).
FIELD = {
    "uv": "ultraviolet_index_clear_sky",
    "humidity": "relative_humidity",
    "dew_point": "dew_point_temperature",
    "fog": "fog_area_fraction",
    "wind": "wind_speed",
}
#: What each detail is called when MET gives none of it.
NAME = {"uv": "UV index", "humidity": "humidity", "dew_point": "dew point", "fog": "fog", "wind": "wind"}
#: WHO's UV bands: the lowest whole index of each, highest first.
UV_BANDS = ((11, "extreme"), (8, "very high"), (6, "high"), (3, "moderate"), (0, "low"))
#: The share of the area in fog, in percent, from which fog is possible, then likely.
FOG_POSSIBLE = 10.0
FOG_LIKELY = 50.0
#: The eight compass points, from north round by east: a sixteenth point is hard to hear.
POINTS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
#: How far apart, in hours, MET's steps are beyond its first days.
STEP_HOURS = 6


def which_detail(what: str) -> str | None:
    """The detail a spoken word names, or None for one not known."""
    # RULE: a detail is known by its own word and the words also taken for it
    word = " ".join(what.lower().replace("-", " ").split())
    return next((kind for kind, words in WORDS.items() if word in words), None)


def _whole(value: float) -> int:
    """A value rounded half up, as said: 2.5 is 3."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _steps(series: list[dict[str, Any]], start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
    """The details MET gives from `start` to `end`; past its hours, the step nearest before."""
    inside = [e for e in series if start <= dt.datetime.fromisoformat(e["time"]) < end]
    if inside:
        return [e["data"]["instant"]["details"] for e in inside]
    # RULE: a time between six hour steps takes the step it falls in
    before = [
        e
        for e in series
        if start - dt.timedelta(hours=STEP_HOURS) < dt.datetime.fromisoformat(e["time"]) <= start
    ]
    return [before[-1]["data"]["instant"]["details"]] if before else []


def _degrees(value: int) -> str:
    return f"minus {-value}" if value < 0 else str(value)


def _humidity(values: list[float]) -> str:
    low, high = _whole(min(values)), _whole(max(values))
    return f"humidity {low} percent" if low == high else f"humidity {low} to {high} percent"


def _dew_point(values: list[float]) -> str:
    low, high = _whole(min(values)), _whole(max(values))
    if low == high:
        return f"dew point {_degrees(low)} {'degree' if abs(low) == 1 else 'degrees'}"
    # RULE: a range of degrees says minus on each side
    return f"dew point {_degrees(low)} to {_degrees(high)} degrees"


def _uv(values: list[float]) -> str:
    index = _whole(max(values))
    # RULE: a uv peak of nothing says no uv
    if index == 0 and len(values) > 1:
        return "no UV"
    # RULE: uv is named by the who bands
    band = next(name for lowest, name in UV_BANDS if index >= lowest)
    return f"UV index {'up to ' if len(values) > 1 else ''}{index} on a clear sky, {band}"


def _fog(values: list[float]) -> str:
    most = max(values)
    # RULE: fog is said by how much of the area it covers
    if most > FOG_LIKELY:
        return "fog likely"
    return "fog possible" if most >= FOG_POSSIBLE else "no fog expected"


def _point(degrees: float) -> str:
    # RULE: the wind comes from where met says in eight points
    return f"the {POINTS[_whole(degrees / 45) % len(POINTS)]}"


def _wind(steps: list[dict[str, Any]]) -> str:
    # RULE: wind over hours is its strongest hour
    strongest = max(steps, key=lambda s: float(s["wind_speed"]))
    speed = _whole(float(strongest["wind_speed"]))
    said = f"wind {'up to ' if len(steps) > 1 else ''}{speed} {'metre' if speed == 1 else 'metres'} a second"
    if "wind_from_direction" in strongest:
        said += f" from {_point(float(strongest['wind_from_direction']))}"
    gust = strongest.get("wind_speed_of_gust")
    # RULE: wind with no gust from met says none
    return said if gust is None else f"{said}, gusts to {_whole(float(gust))}"


def detail_said(kind: str, series: list[dict[str, Any]], start: dt.datetime, end: dt.datetime) -> str | None:
    """The detail's value from `start` to `end` as said, "" when MET gives none, or None for no steps."""
    steps = _steps(series, start, end)
    if not steps:
        return None
    given = [s for s in steps if FIELD[kind] in s]
    if not given:
        return ""
    if kind == "wind":
        return _wind(given)
    values = [float(s[FIELD[kind]]) for s in given]
    said = {"uv": _uv, "humidity": _humidity, "dew_point": _dew_point, "fog": _fog}[kind]
    return said(values)


def not_given(kind: str) -> str:
    """What the voice hears when MET gives no value of the detail for the time asked."""
    # RULE: a detail met does not give that far ahead says so
    return f"MET gives no {NAME[kind]} that far ahead. Ask for a time in the next two days."

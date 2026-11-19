"""What MET's radar sees over the next two hours, as one short sentence for a voice.

The nowcast is MET Norway's nowcast 2.0 complete, a step every five minutes. It covers the
Nordic area only, and it gives a rain rate only where the radar sees well.
"""

from __future__ import annotations

import datetime as dt
import logging
import zoneinfo
from typing import Any

NOWCAST = "https://api.met.no/weatherapi/nowcast/2.0/complete"
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
#: A rate below this, in millimetres an hour, is a trace the radar sees and nobody feels.
TRACE = 0.1
#: A reach of this many minutes or more is said in hours, as MET names it. A nowcast a few
#: minutes old reaches a little short of two hours, and "105 minutes" helps nobody.
# RULE: a reach from a hundred minutes is said in hours
TWO_HOURS = 100
#: Up to this many minutes, the reach is "about" two hours; beyond it, two hours plain.
NEARLY = 115
#: The fewest minutes ahead worth a sentence: one radar step.
STEP = 5
#: How many steps in a row a change must last to be said; one alone is speckle.
SETTLED = 2
#: Rain sooner than this many minutes away is said by how soon, then the time.
HOUR = 60
#: The usual bands, in millimetres an hour: from these, rain is moderate, then heavy.
RAIN_BANDS = (2.5, 10.0)
#: Snow and sleet by their water: a millimetre an hour is about a centimetre of snow.
SNOW_BANDS = (1.0, 2.5)

log = logging.getLogger(__name__)


def called(sky: str) -> str:
    """What falls, by the sky's own word for it."""
    # RULE: the radars rain is called what the sky says falls
    return next((word.title() for word in ("snow", "sleet") if word in sky), "Rain")


def _unrated(*, seen: bool, rated: bool, fresh: bool) -> None:
    """Warn when a seeing radar gives steps but no rain rate, so a renamed field shows."""
    # RULE: a seeing radar with no rain rate is logged
    # RULE: a missing rain rate is logged once for each answer from met
    if fresh and seen and not rated:
        log.warning("MET's nowcast sees but gives no precipitation_rate")


def _ahead(data: dict[str, Any], now: dt.datetime, *, fresh: bool) -> list[tuple[dt.datetime, float]]:
    """The radar's steps from the one under way, each with its rain rate; `fresh` is a new answer."""
    # RULE: a radar that cannot see says nothing
    if data["properties"]["meta"].get("radar_coverage") != "ok":
        return []
    steps = [
        (
            dt.datetime.fromisoformat(entry["time"]),
            entry["data"]["instant"]["details"].get("precipitation_rate"),
        )
        for entry in data["properties"]["timeseries"]
    ]
    rated = [(time, float(rate)) for time, rate in steps if rate is not None]
    _unrated(seen=bool(steps), rated=bool(rated), fresh=fresh)
    # RULE: the step under way counts as now
    start = max((time for time, _ in rated if time <= now), default=now)
    # RULE: past radar steps are left out
    return [(time, rate) for time, rate in rated if time >= start]


def _reach(minutes: int) -> str:
    """The reach, such as "the next two hours" or "the next 95 minutes"."""
    # RULE: the radars reach is said as it is
    if minutes < TWO_HOURS:
        return f"the next {minutes // STEP * STEP} minutes"
    # RULE: a reach near two hours is said as about two hours
    return "the next two hours" if minutes > NEARLY else "about the next two hours"


def _how(rates: list[float], falls: str) -> str:
    """What falls with how hard, such as "Light rain", by the heaviest step of the spell."""
    peak = max(rates)
    # RULE: snow and sleet are banded by their water
    moderate, heavy = RAIN_BANDS if falls == "Rain" else SNOW_BANDS
    # RULE: the rain is called light moderate or heavy by its heaviest step
    word = "Heavy" if peak >= heavy else "Moderate" if peak >= moderate else "Light"
    return f"{word} {falls.lower()}"


def _much(rates: list[float], falls: str) -> str:
    """How much falls over the spell, such as ", about 3 mm", or "" for snow and sleet."""
    # RULE: snow and sleet are never said in millimetres
    if falls != "Rain":
        return ""
    total = sum(rates) * STEP / HOUR
    # RULE: rain falling now says how much
    return ", less than 1 mm" if total < 1 else f", about {int(total + 0.5)} mm"


def _changes(change: dt.datetime, now: dt.datetime, how: str, *, much: str | None) -> str:
    """The change as said: when falling rain stops (with `much`), or when rain comes."""
    at = f"{change.astimezone(OSLO):%H:%M}"
    # RULE: rain falling now says when it stops
    if much is not None:
        return f" {how} until about {at}{much}."
    soon = (change - now).total_seconds() / 60
    # RULE: rain under five minutes away is said as any minute now
    if soon < STEP:
        return f" {how} any minute now."
    # RULE: how soon is rounded to the nearest five minutes
    rounded = int((soon + STEP / 2) // STEP) * STEP
    # RULE: rain within the hour says how soon first
    if soon < HOUR:
        return f" {how} in about {rounded} minutes, around {at}."
    # RULE: rain on the radar says when it starts
    return f" {how} from about {at}."


def _turn(wet: list[bool], start: int) -> int | None:
    """The first step from `start` where the rain changes for good, or None."""
    # RULE: a single step of speckle is not a change
    last = len(wet) - SETTLED + 1
    return next((n for n in range(start, last) if wet[start] not in wet[n : n + SETTLED]), None)


def radar_sentence(data: dict[str, Any], now: dt.datetime, falls: str, *, fresh: bool = True) -> str:
    """A sentence led by a space, such as " Light rain from about 14:00.", or "" with no radar."""
    ahead = _ahead(data, now, fresh=fresh)
    minutes = int((ahead[-1][0] - now).total_seconds() // 60) if ahead else 0
    # RULE: a radar with no steps ahead says nothing
    if minutes < STEP:
        return ""
    return _said(ahead, now, minutes, falls)


def _said(ahead: list[tuple[dt.datetime, float]], now: dt.datetime, minutes: int, falls: str) -> str:
    """The sentence for steps ahead that reach `minutes`: no rain, rain all through, or a change."""
    # RULE: a trace below a tenth of a millimetre is dry
    wet = [rate >= TRACE for _, rate in ahead]
    rates = [rate for _, rate in ahead]
    turn = _turn(wet, 0)
    # RULE: no rain on the radar says no rain
    if turn is None and not wet[0]:
        return f" No {falls.lower()} for {_reach(minutes)}."
    # RULE: rain all through says so
    if turn is None:
        return f" {_how(rates, falls)} for {_reach(minutes)}{_much(rates, falls)}."
    spell = rates[:turn] if wet[0] else rates[turn : _turn(wet, turn)]
    much = _much(spell, falls) if wet[0] else None
    return _changes(ahead[turn][0], now, _how(spell, falls), much=much)

"""weather_now's radar sentence, from a fake MET nowcast five minutes a step.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026, and the sky is cloudy.
"""

import asyncio
import datetime as dt
import logging
import time

import httpx
import pytest
from fakes import START, FakeApi, forecast, radar
from test_weather_now import AGENT, HOME, Voice, ask

from weather_mcp import weather as weather_module
from weather_mcp.cache import CachedClient
from weather_mcp.config import Config
from weather_mcp.places import PlaceFinder
from weather_mcp.weather import Weather

NOW = "7 degrees and cloudy in Testheim."
DRY, WET = 0.0, 1.2
#: Two hours ahead, five minutes a step, from the step under way.
TWO_HOURS = 25


def _say(rates, **api):
    answer = ask(api=FakeApi(nowcast=radar(rates), **api))
    assert answer["success"], answer
    return answer["say"]


def test_no_rain_on_the_radar_says_dry():
    assert _say([DRY] * TWO_HOURS) == f"{NOW} Dry for the next two hours."


def test_rain_on_the_radar_says_when_it_starts():
    """An hour or more off, the time alone is said."""
    assert _say([DRY] * 12 + [WET] * 13) == f"{NOW} Rain from about 14:00."


def test_rain_falling_now_says_when_it_stops():
    assert _say([WET] * 8 + [DRY] * 17) == f"{NOW} Rain until about 13:40."


def test_rain_all_through_says_so():
    assert _say([WET] * TWO_HOURS) == f"{NOW} Rain for the next two hours."


def test_a_trace_below_a_tenth_of_a_millimetre_is_dry():
    assert _say([0.09] * TWO_HOURS) == f"{NOW} Dry for the next two hours."


def test_a_tenth_of_a_millimetre_is_rain():
    assert _say([DRY] * 5 + [0.1] * 20) == f"{NOW} Rain in about 25 minutes, around 13:25."


def test_the_radars_reach_is_said_as_it_is():
    """A nowcast that reaches an hour says an hour's worth, never two."""
    assert _say([DRY] * 13) == f"{NOW} Dry for the next 60 minutes."


def test_a_reach_near_two_hours_is_said_as_about_two_hours():
    """A nowcast a few minutes old reaches a little short of two hours; "105 minutes" is no help."""
    assert _say([DRY] * 21) == f"{NOW} Dry for about the next two hours."
    assert _say([DRY] * 24) == f"{NOW} Dry for about the next two hours."
    assert _say([DRY] * 20) == f"{NOW} Dry for the next 95 minutes."


def test_past_radar_steps_are_left_out():
    """Rain half an hour ago is over; the step under way is the first that counts."""
    rates = [WET] * 6 + [DRY] * TWO_HOURS
    answer = ask(api=FakeApi(nowcast=radar(rates, start=START - dt.timedelta(minutes=30))))
    assert answer["say"] == f"{NOW} Dry for the next two hours."


def test_the_step_under_way_counts_as_now():
    api = FakeApi(nowcast=radar([WET] + [DRY] * TWO_HOURS))
    api.clock.advance(2)
    assert ask(api=api)["say"] == f"{NOW} Rain until about 13:05."


@pytest.mark.parametrize(
    ("symbol", "word"), [("snow", "Snow"), ("lightsleet", "Sleet"), ("heavyrain", "Rain")]
)
def test_the_radars_rain_is_called_what_the_sky_says_falls(symbol, word):
    api = FakeApi(body=forecast(symbol=symbol), nowcast=radar([DRY] * 5 + [WET] * 20))
    assert ask(api=api)["say"].endswith(f" {word} in about 25 minutes, around 13:25.")


@pytest.mark.parametrize("coverage", ["no coverage", "temporarily unavailable"])
def test_a_radar_that_cannot_see_says_nothing(coverage):
    """MET leaves the rates out then; should one come anyway, the coverage still decides."""
    blind = radar([WET] * TWO_HOURS)
    blind["properties"]["meta"]["radar_coverage"] = coverage
    assert ask(api=FakeApi(nowcast=blind))["say"] == NOW


@pytest.mark.parametrize("coverage", ["no coverage", "temporarily unavailable"])
def test_a_blind_radar_as_met_sends_it_adds_nothing(coverage):
    assert ask(api=FakeApi(nowcast=radar([DRY] * TWO_HOURS, coverage=coverage)))["say"] == NOW


def test_a_radar_with_no_steps_ahead_says_nothing():
    answer = ask(api=FakeApi(nowcast=radar([WET] * 6, start=START.replace(hour=8))))
    assert answer["say"] == NOW


def test_a_radar_outside_its_area_leaves_the_answer_as_it_was():
    answer = ask(api=FakeApi())
    assert answer == {"success": True, "say": NOW, "place": "Testheim"}


@pytest.mark.parametrize("status", [500, 403, 429])
def test_a_radar_that_fails_leaves_the_answer_as_it_was(status):
    answer = ask(api=FakeApi(nowcast=radar([WET] * TWO_HOURS), nowcast_broken=status))
    assert answer == {"success": True, "say": NOW, "place": "Testheim"}


def test_the_radar_is_asked_for_the_same_point_as_the_forecast():
    api = FakeApi(nowcast=radar([DRY] * TWO_HOURS))
    ask(api=api)
    sent = [r.url.params for r in api.requests if r.url.path.endswith("/nowcast/2.0/complete")]
    assert [(p["lat"], p["lon"]) for p in sent] == [("61.00", "9.00")]


def test_the_radar_at_a_position_is_never_written_to_the_cache_file(tmp_path):
    api, store = FakeApi(nowcast=radar([DRY] * TWO_HOURS)), tmp_path / "forecasts.json"

    async def go():
        async with httpx.AsyncClient(transport=api.transport()) as http:
            weather = Weather(
                Config(contact="https://example.org", home=HOME),
                CachedClient(http, AGENT, clock=api.clock, store=store),
                PlaceFinder(http, AGENT),
            )
            return await weather.now(lat=61.0, lon=9.0)

    answer = asyncio.run(go())
    assert answer["say"].endswith("Dry for the next two hours.")
    assert "61.00" not in (store.read_text() if store.exists() else "")


def test_an_odd_radar_answer_leaves_the_answer_as_it_was():
    odd = {"type": "Feature", "properties": {"meta": {"radar_coverage": "ok"}}}
    answer = ask(api=FakeApi(nowcast=odd))
    assert answer == {"success": True, "say": NOW, "place": "Testheim"}


def test_a_slow_radar_leaves_the_answer_as_it_was(monkeypatch):
    """A radar that keeps the voice waiting is dropped, and the temperature still comes."""
    monkeypatch.setattr(weather_module, "RADAR_WITHIN", 0.2)
    answer = ask(api=FakeApi(nowcast=radar([DRY] * TWO_HOURS), nowcast_delay=5))
    assert answer == {"success": True, "say": NOW, "place": "Testheim"}


def test_the_radar_is_given_a_few_seconds():
    assert 1 <= weather_module.RADAR_WITHIN <= 4


@pytest.mark.parametrize(
    ("rates", "said"),
    [
        ([DRY] * 5 + [WET] + [DRY] * 19, "Dry for the next two hours."),
        ([WET] * 5 + [DRY] + [WET] * 19, "Rain for the next two hours."),
        ([DRY] * 24 + [WET], "Dry for the next two hours."),
    ],
)
def test_a_single_step_of_speckle_is_not_a_change(rates, said):
    assert _say(rates) == f"{NOW} {said}"


def test_a_seeing_radar_with_no_rain_rate_is_logged(caplog):
    """Should MET rename the field, the log says so, rather than the sentence just going quiet."""
    unrated = radar([DRY] * TWO_HOURS)
    for step in unrated["properties"]["timeseries"]:
        del step["data"]["instant"]["details"]["precipitation_rate"]
    with caplog.at_level(logging.WARNING):
        answer = ask(api=FakeApi(nowcast=unrated))
    assert answer["say"] == NOW
    assert "precipitation_rate" in caplog.text
    assert "61.00" not in caplog.text


def test_rain_within_the_hour_says_how_soon_first():
    """What the listener acts on comes first: the wait, then the time it gives."""
    assert _say([DRY] * 9 + [WET] * 16) == f"{NOW} Rain in about 45 minutes, around 13:45."


def test_the_forecast_and_the_radar_are_asked_at_once():
    """Each takes 1.5 s; asked one after the other they would take 3."""
    api = FakeApi(nowcast=radar([DRY] * TWO_HOURS), delay=1.5)
    began = time.monotonic()
    answer = ask(api=api)
    assert answer["say"] == f"{NOW} Dry for the next two hours."
    assert time.monotonic() - began < 2.5


def test_a_missing_rain_rate_is_logged_once_for_each_answer_from_met(caplog):
    """The nowcast is kept until it expires; asking again within that logs nothing more."""
    unrated = radar([DRY] * TWO_HOURS)
    for step in unrated["properties"]["timeseries"]:
        del step["data"]["instant"]["details"]["precipitation_rate"]
    voice = Voice(FakeApi(nowcast=unrated))
    try:
        with caplog.at_level(logging.WARNING):
            voice.now()
            voice.now()
    finally:
        voice.close()
    assert caplog.text.count("precipitation_rate") == 1


def test_how_soon_is_rounded_to_the_nearest_five_minutes():
    """At 13:02:30, rain at 13:25 is 22.5 minutes off: said as 25, as the time it gives."""
    api = FakeApi(nowcast=radar([DRY] * 5 + [WET] * 20))
    api.clock.advance(2.5)
    assert ask(api=api)["say"] == f"{NOW} Rain in about 25 minutes, around 13:25."


def test_how_soon_is_never_said_as_less_than_five_minutes():
    api = FakeApi(nowcast=radar([DRY] + [WET] * 24))
    api.clock.advance(4)
    assert ask(api=api)["say"] == f"{NOW} Rain in about 5 minutes, around 13:05."

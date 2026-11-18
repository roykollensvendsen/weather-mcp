"""weather_now's radar sentence, from a fake MET nowcast five minutes a step.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026, and the sky is cloudy.
"""

import asyncio
import datetime as dt

import httpx
import pytest
from fakes import START, FakeApi, forecast, radar
from test_weather_now import AGENT, HOME, ask

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
    assert _say([DRY] * 5 + [WET] * 20) == f"{NOW} Rain from about 13:25."


def test_rain_falling_now_says_when_it_stops():
    assert _say([WET] * 8 + [DRY] * 17) == f"{NOW} Rain until about 13:40."


def test_rain_all_through_says_so():
    assert _say([WET] * TWO_HOURS) == f"{NOW} Rain for the next two hours."


def test_a_trace_below_a_tenth_of_a_millimetre_is_dry():
    assert _say([0.09] * TWO_HOURS) == f"{NOW} Dry for the next two hours."


def test_a_tenth_of_a_millimetre_is_rain():
    assert _say([DRY] * 5 + [0.1] * 20) == f"{NOW} Rain from about 13:25."


def test_the_radars_reach_is_said_as_it_is():
    """A nowcast that reaches an hour says an hour's worth, never two."""
    assert _say([DRY] * 13) == f"{NOW} Dry for the next 60 minutes."


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
    assert ask(api=api)["say"].endswith(f" {word} from about 13:25.")


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


def test_a_radar_that_fails_leaves_the_answer_as_it_was_on_an_odd_answer():
    odd = {"type": "Feature", "properties": {"meta": {"radar_coverage": "ok"}}}
    answer = ask(api=FakeApi(nowcast=odd))
    assert answer == {"success": True, "say": NOW, "place": "Testheim"}

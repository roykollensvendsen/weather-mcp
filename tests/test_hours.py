"""weather_hours, through the MCP server, against a fake MET shaped as its real answer is.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026. MET gives hours until the 17th
and six-hour blocks after that, to 01:00 on Tuesday the 24th; Friday the 20th is a block day.
"""

import pytest
from fakes import FakeApi, met_like
from test_weather_now import Voice


def _plain(local):
    """Each hour's temperature is its clock hour, so the range shows which hours were used.

    Cloudy before 16:00 and clear after, rain only at 15:00, and strong wind only at 17:00.
    """
    h = local.hour
    return float(h), "cloudy" if h < 16 else "clearsky_day", 1.0 if h == 15 else 0.0, 9.0 if h == 17 else 3.0


def _hours(**asked):
    voice = Voice(FakeApi(body=met_like(_plain)))
    try:
        result = voice.loop.run_until_complete(voice.server.call_tool("weather_hours", asked))
        return result.structured_content
    finally:
        voice.close()


def _say(**asked):
    answer = _hours(**asked)
    assert answer["success"], answer
    return answer["say"]


ONE = "Today at 15:00 in Testheim: 15 degrees, cloudy, 1 millimetre of rain, wind 3 metres a second."


def test_one_hour_says_its_temperature_sky_rain_and_wind():
    assert _say(from_time="15") == ONE


@pytest.mark.parametrize("said", ["15:00", "15.00", "kl. 15", "klokka 15", "3 pm"])
def test_an_hour_said_in_either_language_is_the_same_hour(said):
    assert _say(from_time=said) == ONE


def test_one_time_asked_about_is_that_one_hour():
    """An end equal to the start is the same as no end: that one hour."""
    assert _say(from_time="15", to_time="15") == ONE


def test_a_span_says_the_range_the_rain_and_the_strongest_wind():
    assert _say(from_time="14", to_time="18") == (
        "Today from 14:00 to 18:00 in Testheim: 14 to 17 degrees, cloudy, then clear,"
        " 1 millimetre of rain, wind up to 9 metres a second."
    )


def test_a_sky_that_changes_is_said_as_it_goes():
    assert ", cloudy, then clear," in _say(from_time="14", to_time="18")
    assert ", cloudy, dry," in _say(from_time="13", to_time="15")


def test_another_day_by_its_name():
    assert _say(day="i morgen", from_time="8", to_time="12") == (
        "Tomorrow from 08:00 to 12:00 in Testheim: 8 to 11 degrees, cloudy, dry,"
        " wind up to 3 metres a second."
    )


def test_an_end_before_the_start_runs_past_midnight():
    """From 22 to 2 is the night into tomorrow: 22:00, 23:00, 00:00 and 01:00."""
    assert _say(from_time="22", to_time="2") == (
        "Today from 22:00 to 02:00 in Testheim: 0 to 23 degrees, clear, then cloudy, dry,"
        " wind up to 3 metres a second."
    )


def test_a_time_already_gone_is_refused():
    answer = _hours(from_time="11")
    assert answer == {"success": False, "say": "11:00 has passed. Ask for a time to come."}


def test_the_hour_now_is_not_gone():
    assert _say(from_time="13").startswith("Today at 13:00 in Testheim: 13 degrees, cloudy, dry,")


def test_a_time_that_has_begun_is_answered_from_now():
    assert _say(from_time="11", to_time="15") == (
        "Today from now to 15:00 in Testheim: 13 to 14 degrees, cloudy, dry, wind up to 3 metres a second."
    )


def test_an_hour_counts_when_its_stretch_overlaps_the_time_asked_about():
    """On Friday MET gives a block from 13:00 to 19:00, which covers 14:00 to 16:00."""
    assert _say(day="fredag", from_time="14", to_time="16").startswith(
        "Friday from 14:00 to 16:00 in Testheim: about 13 degrees, cloudy, dry, wind 3 metres a second."
    )


def test_a_time_in_six_hour_blocks_names_the_block():
    """A block's sky and rain are for all its six hours, so the answer says which hours."""
    say = _say(day="fredag", from_time="14", to_time="16")
    assert say.endswith(" MET gives six-hour steps that far ahead, so this is for 13:00 to 19:00.")
    assert "six-hour" not in _say(from_time="14", to_time="18")


def test_a_time_past_the_forecast_says_how_far_it_reaches():
    answer = _hours(day="25.11", from_time="12")
    assert answer == {"success": False, "say": "MET's forecast reaches to Tuesday 24.11 at 01:00."}


@pytest.mark.parametrize("said", ["soon", "fifteen", "25"])
def test_an_unknown_time_is_asked_about_not_guessed(said):
    answer = _hours(from_time=said)
    assert answer == {"success": False, "say": "Which time? Say an hour such as 15 or 15:00."}
    assert _hours(from_time="15", to_time=said) == answer


def test_an_unknown_or_gone_day_is_said_as_for_the_forecast():
    assert _hours(day="someday", from_time="15")["say"].startswith("Which day?")
    assert (
        _hours(day="13.11", from_time="15")["say"] == "That day has passed. Ask for today or a day to come."
    )


def test_the_hours_tool_says_when_to_use_it_and_when_not():
    voice = Voice()
    try:
        tools = voice.tools()
    finally:
        voice.close()
    hours = tools["weather_hours"]
    assert "weather_forecast" in hours.description
    assert "weather_week" in hours.description
    assert "weather_hours" in tools["weather_forecast"].description
    assert {"from_time", "to_time", "day", "place", "lat", "lon", "accuracy_m"} <= set(
        hours.input_schema["properties"]
    )
    assert hours.input_schema["required"] == ["from_time"]
    assert "15.00" in hours.input_schema["properties"]["from_time"]["description"]
    assert hours.annotations.read_only_hint

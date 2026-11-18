"""weather_week, through the MCP server, against a fake MET shaped as its real answer is.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026. MET gives hours until the
17th and six-hour blocks after that, to Monday the 23rd.
"""

import pytest
from fakes import FakeApi, met_like
from test_weather_now import PHONE, Voice

#: Each day's low, high, rain an hour from noon to 18:00, the sky then, and the wind.
DAYS = {
    15: (2.0, 7.0, 0.5, "rain", 6.0),
    16: (3.0, 8.0, 0.0, "cloudy", 4.0),
    17: (1.0, 5.0, 0.0, "cloudy", 12.0),
    18: (1.0, 6.0, 0.0, "cloudy", 13.0),
    19: (-3.0, 0.0, 8 / 6, "snow", 5.0),
}


def _days(local):
    low, high, rain, sky, wind = DAYS.get(local.day, (30.0, 30.0, 10.0, "heavyrain", 20.0))
    midday = 12 <= local.hour < 18
    return (high if local.hour >= 12 else low), (sky if midday else "cloudy"), (rain if midday else 0.0), wind


def _week(at=_days, **asked):
    voice = Voice(FakeApi(body=met_like(at)))
    try:
        result = voice.loop.run_until_complete(voice.server.call_tool("weather_week", asked))
        return result.structured_content
    finally:
        voice.close()


WEEK = (
    "The next 5 days in Testheim: Tomorrow: 2 to 7 degrees, rain. Monday: 3 to 8 degrees, dry."
    " Tuesday and Wednesday: about 1 to 6 degrees, dry, wind up to 13. Thursday: about minus 3"
    " to 0 degrees, snow. Wettest is Thursday, with 8 millimetres; driest is Monday."
)


def test_the_week_says_one_short_line_a_day_from_tomorrow():
    answer = _week()
    assert answer["success"], answer
    assert answer["say"] == WEEK


def test_days_that_sound_alike_are_said_together():
    assert " Tuesday and Wednesday: about 1 to 6 degrees, dry, wind up to 13." in _week()["say"]


def test_a_week_line_says_the_wind_only_when_it_is_strong():
    """Six metres a second on Sunday is left out; twelve and thirteen are said."""
    say = _week()["say"]
    assert "Tomorrow: 2 to 7 degrees, rain." in say
    assert "wind up to 13" in say


def test_the_week_ends_with_its_wettest_and_driest_day():
    assert _week()["say"].endswith(" Wettest is Thursday, with 8 millimetres; driest is Monday.")


def test_a_dry_week_says_so_once():
    say = _week(lambda _local: (2.0, "cloudy", 0.0, 3.0))["say"]
    assert say == "The next 5 days in Testheim: Tomorrow to Thursday: about 2 degrees, dry. Dry every day."


def test_the_week_runs_until_the_day_asked():
    assert _week(until="tirsdag")["say"].startswith("The next 3 days in Testheim: Tomorrow: 2 to 7 degrees")
    assert " Tuesday: about 1 to 5 degrees, dry, wind up to 12." in _week(until="på tirsdag")["say"]


def test_the_week_stops_where_the_forecast_does():
    """Asked to the 30th, it says the nine days MET covers, to Monday the 23rd, and no more."""
    say = _week(lambda _local: (2.0, "cloudy", 0.0, 3.0), until="30.11")["say"]
    assert say.startswith("The next 9 days in Testheim: Tomorrow to Monday 23.11: about 2 degrees, dry.")


@pytest.mark.parametrize(
    ("until", "said"),
    [
        ("i dag", "For today alone, ask for today's forecast."),
        ("10.11", "That day has passed. Ask for today or a day to come."),
        ("someday", "Which day? Say today, tomorrow, a weekday or a date such as 20.11."),
    ],
)
def test_a_week_to_no_day_to_come_is_refused(until, said):
    answer = _week(until=until)
    assert not answer["success"]
    assert answer["say"] == said


def test_every_sentence_of_the_week_is_short():
    """A voice reads it aloud: no sentence over 30 words."""
    sentences = [s for s in _week()["say"].replace(": ", ". ").split(". ") if s]
    assert max(len(s.split()) for s in sentences) <= 30


def test_the_week_where_the_phone_is():
    assert _week(**PHONE)["say"].startswith("The next 5 days where you are:")


def test_the_week_tool_says_when_to_use_it_and_when_not():
    voice = Voice()
    try:
        tools = voice.tools()
    finally:
        voice.close()
    week, day = tools["weather_week"], tools["weather_forecast"]
    assert "weather_forecast" in week.description
    assert "weather_week" in day.description
    assert {"until", "place", "lat", "lon", "accuracy_m"} <= set(week.input_schema["properties"])
    assert "søndag" in week.input_schema["properties"]["until"]["description"]
    assert week.annotations.read_only_hint


def test_a_week_of_even_rain_names_no_wettest_day():
    """With much the same rain every day, no day is the wettest or the driest."""
    say = _week(lambda local: (2.0, "rain", 0.5 if 12 <= local.hour < 18 else 0.0, 3.0))["say"]
    assert say.endswith(" Much the same rain every day, up to 3 millimetres.")
    assert "Wettest" not in say

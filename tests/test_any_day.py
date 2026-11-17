"""weather_forecast for any day MET covers, against a fake MET shaped as its real answer is.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026. MET gives hours until the
17th and six-hour blocks after that, to Monday the 23rd, so Friday the 20th is a block day.
"""

import datetime as dt

import pytest
from fakes import FakeApi, hourly, met_like
from test_weather_forecast import _tomorrow
from test_weather_now import Voice


def _friday(local):
    """Friday the 20th, made plain; every other day is wild, so a leak across midnight shows.

    Its blocks begin at 01, 07, 13 and 19 in Oslo.
    """
    if local.day != 20:
        return 30.0, "heavysnow", 10.0, 20.0
    return {
        1: (1.0, "fair_night", 0.0, 2.0),
        7: (3.0, "cloudy", 0.0, 3.0),
        13: (6.0, "lightrain", 0.5, 8.0),
        19: (4.0, "clearsky_night", 0.0, 2.0),
    }[local.hour]


def _ask(at, **asked):
    voice = Voice(FakeApi(body=met_like(at)))
    try:
        return voice.forecast(**asked)
    finally:
        voice.close()


FRIDAY = (
    "Friday in Testheim: about 1 to 6 degrees, 3 millimetres of rain and wind up to 8 metres a"
    " second; cloudy in the morning, light rain at midday and clear in the evening."
)


@pytest.mark.parametrize("said", ["fredag", "Friday", "på fredag", "on friday", "20.11", "2026-11-20"])
def test_a_weekday_or_a_date_gives_that_days_forecast(said):
    answer = _ask(_friday, day=said)
    assert answer["success"], answer
    assert answer["say"] == FRIDAY


def test_a_day_in_six_hour_blocks_says_about_for_its_range():
    """Four readings a day can miss the highs and lows, so the range is said as rough."""
    assert _ask(_friday, day="fredag")["say"].startswith("Friday in Testheim: about 1 to 6 degrees,")
    hourly_day = _ask(_tomorrow, day="i morgen")["say"]
    assert hourly_day.startswith("Tomorrow in Testheim: 2 to 7 degrees,")


def test_norwegian_tomorrow_is_tomorrow():
    assert _ask(_tomorrow, day="i morgen")["say"] == _ask(_tomorrow, day="tomorrow")["say"]


def test_a_blocks_rain_counts_on_the_day_it_starts():
    """The 19:00 block runs past midnight; its rain is the evening's, not the next morning's."""

    def evening_rain(local):
        rain = 1.0 if (local.day, local.hour) == (19, 19) else 0.0
        return 2.0, "rain" if rain else "cloudy", rain, 2.0

    assert "6 millimetres of rain" in _ask(evening_rain, day="torsdag")["say"]
    assert "no rain" in _ask(evening_rain, day="fredag")["say"]


def test_rain_is_counted_once_for_each_stretch_of_time():
    """An hour that gives only its six-hour block covers the hours after it, whose rain is in it."""
    body = hourly(_tomorrow)
    for entry in body["properties"]["timeseries"]:
        if entry["time"] == "2026-11-15T11:00:00Z":  # 12:00 in Oslo, the first rainy hour
            del entry["data"]["next_1_hours"]
            entry["data"]["next_6_hours"] = {
                "summary": {"symbol_code": "lightrain"},
                "details": {"precipitation_amount": 3.0},  # 12:00 to 18:00, each hour's 0.5
            }
    voice = Voice(FakeApi(body=body))
    try:
        say = voice.forecast(day="tomorrow")["say"]
    finally:
        voice.close()
    assert "3 millimetres of rain" in say  # not 3.0 again plus the five hours after it


def test_a_day_past_the_forecast_says_how_far_it_reaches():
    """The last entry carries no block, so Monday the 23rd is the last whole day."""
    answer = _ask(_friday, day="24.11")
    assert not answer["success"]
    assert answer["say"] == "MET's forecast reaches to Monday 23.11."


def test_a_day_already_gone_is_refused():
    answer = _ask(_friday, day="10.11")
    assert not answer["success"]
    assert answer["say"] == "That day has passed. Ask for today or a day to come."


def test_an_unknown_day_is_asked_about_not_guessed():
    answer = _ask(_friday, day="someday")
    assert not answer["success"]
    assert answer["say"] == "Which day? Say today, tomorrow, a weekday or a date such as 20.11."


def test_a_weekday_a_week_away_is_said_with_its_date():
    """Monday the 23rd is nine days on, so "Monday" alone could mean the 16th."""
    answer = _ask(lambda _local: (2.0, "cloudy", 0.0, 2.0), day="23.11")
    assert answer["say"].startswith("Monday 23.11 in Testheim: about 2 degrees,")


def test_today_is_still_today_by_any_word():
    api = FakeApi(body=met_like(lambda _local: (2.0, "cloudy", 0.0, 2.0)))
    api.clock.now = dt.datetime(2026, 11, 14, 12, 30, tzinfo=dt.UTC)
    voice = Voice(api)
    try:
        assert voice.forecast(day="i dag")["say"].startswith("Today in Testheim: 2 degrees,")
    finally:
        voice.close()

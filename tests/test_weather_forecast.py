"""weather_forecast, through the MCP server, against a fake MET that answers hour by hour.

The fake's clock starts at 12:00 UTC on 14 November, 13:00 in Oslo. Home is made up.
"""

import datetime as dt

from fakes import START, FakeApi, hourly
from test_weather_now import PHONE, Voice


def _tomorrow(local):
    """The 15th, made plain; the days around it are wild, so a leak across midnight shows."""
    if local.day != 15:
        return (-10.0 if local.day == 14 else 30.0), "heavysnow", 10.0, 20.0
    h = local.hour
    temperature = 7.0 if h == 14 else 2.0
    symbol = (
        "cloudy"
        if 6 <= h < 12
        else "lightrain"
        if 12 <= h < 17
        else "clearsky_night"
        if 17 <= h < 23
        else "fair_night"
    )
    rain = 0.5 if 12 <= h < 18 else 0.0
    wind = 6.4 if h == 15 else 2.0
    return temperature, symbol, rain, wind


def _forecast(at=_tomorrow, **asked):
    voice = Voice(FakeApi(body=hourly(at)))
    try:
        return voice.forecast(**asked)
    finally:
        voice.close()


def test_tomorrow_says_the_range_the_rain_the_wind_and_the_day_in_three_parts():
    answer = _forecast()
    assert answer["success"]
    assert answer["say"] == (
        "Tomorrow in Testheim: 2 to 7 degrees, 3 millimetres of rain and wind up to 6 metres a second;"
        " cloudy in the morning, light rain at midday and clear in the evening."
    )


def test_a_day_with_one_sky_says_it_once():
    answer = _forecast(lambda _local: (3.0, "cloudy", 0.0, 1.0))
    assert answer["say"] == (
        "Tomorrow in Testheim: 3 degrees, no rain and wind up to 1 metre a second; cloudy all day."
    )


def test_a_cold_day_says_minus_and_snow():
    answer = _forecast(lambda local: (-4.0 if local.hour < 12 else -1.0, "lightsnow", 0.3, 2.0))
    assert answer["say"].startswith("Tomorrow in Testheim: minus 4 to minus 1 degrees, 7 millimetres of snow")


def test_a_little_rain_is_not_rounded_away():
    answer = _forecast(
        lambda local: (
            5.0,
            "lightrain" if local.hour == 9 else "cloudy",
            0.2 if local.hour == 9 else 0.0,
            2.0,
        )
    )
    assert ", a little rain and wind" in answer["say"]


def test_today_leaves_out_what_has_passed():
    def today(local):
        if local.day != 14:
            return 30.0, "heavysnow", 10.0, 20.0
        if local.hour < 13:  # before now, 13:00 in Oslo, so never said
            return -8.0, "fog", 5.0, 15.0
        return 4.0, "rain" if local.hour < 17 else "cloudy", 1.0 if local.hour < 17 else 0.0, 3.0

    voice = Voice(FakeApi(body=hourly(today, start=START - dt.timedelta(hours=12))))
    try:
        answer = voice.forecast(day="today")
    finally:
        voice.close()
    assert answer["say"] == (
        "Today in Testheim: 4 degrees, 4 millimetres of rain and wind up to 3 metres a second;"
        " rain at midday and cloudy in the evening."
    )


def test_a_day_beyond_the_forecast_is_said_plainly():
    voice = Voice()  # the fake's plain answer holds one hour, today
    try:
        answer = voice.forecast()
        assert not answer["success"]
        assert answer["say"] == "MET has no forecast for tomorrow yet."
    finally:
        voice.close()


def test_tomorrow_where_the_phone_is():
    answer = _forecast(**PHONE)
    assert answer["say"].startswith("Tomorrow where you are: 2 to 7 degrees")


def test_a_named_place_comes_before_the_position_for_tomorrow():
    assert _forecast(place="Haugen", **PHONE)["say"].startswith("Tomorrow in Haugen:")


def test_now_and_tomorrow_share_one_forecast_from_met():
    """The same locationforecast answers both, and the cache honours its Expires."""
    voice = Voice(FakeApi(body=hourly(_tomorrow)))
    try:
        voice.now()
        voice.forecast()
        assert len(voice.api.forecast_requests()) == 1
    finally:
        voice.close()


def test_a_forecast_comes_within_the_deadline():
    voice = Voice(FakeApi(body=hourly(_tomorrow), delay=1.0), answer_within=0.1)
    try:
        answer = voice.forecast()
        assert not answer["success"]
        assert "slow" in answer["say"]
    finally:
        voice.close()


def test_the_forecast_tool_asks_for_the_phones_position_and_the_day():
    voice = Voice()
    try:
        tool = voice.tools()["weather_forecast"]
        assert {"day", "place", "lat", "lon", "accuracy_m"} <= set(tool.input_schema["properties"])
        assert "phone's position" in tool.description
        day = tool.input_schema["properties"]["day"]
        assert day["type"] == "string"
        assert "tomorrow" in day["description"].lower()
        assert "fredag" in day["description"]  # Norwegian words are taken too
    finally:
        voice.close()


def test_a_forecast_holds_only_its_own_day():
    """The fake's days around the 15th are wild, so an hour across midnight would show."""
    say = _forecast()["say"]
    assert "minus 10" not in say
    assert "30" not in say
    assert "snow" not in say


def test_today_late_in_the_evening_says_the_day_is_nearly_over():
    """At 23:30 MET's first hour may already be tomorrow's; there is a forecast, just not for today."""
    api = FakeApi(body=hourly(_tomorrow, start=dt.datetime(2026, 11, 14, 23, 0, tzinfo=dt.UTC)))
    api.clock.now = dt.datetime(2026, 11, 14, 22, 30, tzinfo=dt.UTC)  # 23:30 in Oslo
    voice = Voice(api)
    try:
        answer = voice.forecast(day="today")
    finally:
        voice.close()
    assert not answer["success"]
    assert answer["say"] == "Today is nearly over. Ask for tomorrow instead."

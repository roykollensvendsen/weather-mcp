"""weather_detail, through the MCP server, against a fake MET complete forecast.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026. MET gives hours from 13:00 for
sixty hours, then, where a test asks, steps six hours apart with no fog, UV or gust.
"""

import pytest
from fakes import COMPLETE_PATH, FORECAST_PATH, START, FakeApi, detailed
from test_weather_now import Voice


def _plain(local):
    """Each hour's humidity is 60 plus its clock hour and its dew point its hour less 16.

    The wind is 3 m/s from the south-west, gusting to 7, with no fog and no UV.
    """
    h = local.hour
    return {
        "relative_humidity": 60.0 + h,
        "dew_point_temperature": h - 16.0,
        "fog_area_fraction": 0.0,
        "ultraviolet_index_clear_sky": 0.0,
        "wind_from_direction": 225.0,
        "wind_speed": 3.0,
        "wind_speed_of_gust": 7.0,
    }


def _detail(api=None, **asked):
    voice = Voice(api or FakeApi(complete=detailed(_plain)))
    try:
        result = voice.loop.run_until_complete(voice.server.call_tool("weather_detail", asked))
        return result.structured_content
    finally:
        voice.close()


def _say(api=None, **asked):
    answer = _detail(api, **asked)
    assert answer["success"], answer
    return answer["say"]


def _with(**changed):
    """A fake whose every hour is as _plain's, but with these details changed."""
    return FakeApi(complete=detailed(lambda local: _plain(local) | changed))


def test_humidity_at_an_hour_is_said_in_percent():
    assert _say(what="humidity", from_time="15") == "Today at 15:00 in Testheim: humidity 75 percent."


def test_a_detail_with_no_time_is_for_now():
    assert _say(what="humidity") == "Now in Testheim: humidity 73 percent."


def test_a_detail_over_hours_is_said_as_its_range():
    said = _say(what="humidity", from_time="14", to_time="18")
    assert said == "Today from 14:00 to 18:00 in Testheim: humidity 74 to 77 percent."


def test_another_day_with_no_time_is_the_whole_day():
    assert _say(what="humidity", day="tomorrow") == "Tomorrow in Testheim: humidity 60 to 83 percent."


@pytest.mark.parametrize(
    ("hour", "said"), [("15", "minus 1 degree"), ("17", "1 degree"), ("20", "4 degrees"), ("16", "0 degrees")]
)
def test_the_dew_point_is_said_in_degrees(hour, said):
    assert _say(what="dew point", from_time=hour).endswith(f"in Testheim: dew point {said}.")


def test_a_range_of_degrees_says_minus_on_each_side():
    said = _say(what="dew_point", from_time="13", to_time="16")
    assert said.endswith("in Testheim: dew point minus 3 to minus 1 degrees.")


@pytest.mark.parametrize(
    ("index", "band"),
    [
        (2.0, "low"),
        (3.0, "moderate"),
        (5.0, "moderate"),
        (6.0, "high"),
        (7.0, "high"),
        (8.0, "very high"),
        (10.0, "very high"),
        (11.0, "extreme"),
    ],
)
def test_uv_is_named_by_the_who_bands(index, band):
    """WHO's bands: 0 to 2 low, 3 to 5 moderate, 6 and 7 high, 8 to 10 very high, 11 up extreme."""
    said = _say(_with(ultraviolet_index_clear_sky=index), what="uv", from_time="15")
    assert said == f"Today at 15:00 in Testheim: UV index {round(index)} on a clear sky, {band}."


def test_uv_with_no_time_is_the_rest_of_todays_peak():
    """The day's peak, from now: an hour already gone, and tomorrow's, are left out."""

    def sun(local):
        peak = {12: 9.0, 14: 4.0, 15: 3.0}.get(local.hour, 1.0) if local.day == 14 else 9.0
        return _plain(local) | {"ultraviolet_index_clear_sky": peak}

    said = _say(FakeApi(complete=detailed(sun, start=START.replace(hour=11))), what="uv")
    assert said == "Today in Testheim: UV index up to 4 on a clear sky, moderate."


@pytest.mark.parametrize(
    ("fraction", "said"),
    [(9.9, "no fog expected"), (10.0, "fog possible"), (50.0, "fog possible"), (50.1, "fog likely")],
)
def test_fog_is_said_by_how_much_of_the_area_it_covers(fraction, said):
    """MET's fog_area_fraction is the share of the area in fog, not a chance of it."""
    assert _say(_with(fog_area_fraction=fraction), what="fog", from_time="15").endswith(f": {said}.")


@pytest.mark.parametrize(
    ("what", "said"),
    [
        ("visibility", "fog possible"),
        ("UV-index", "UV index 0 on a clear sky, low"),
        ("Dew  Point", "dew point minus 1 degree"),
        ("gusts", "wind 3 metres a second from the south-west, gusts to 7"),
    ],
)
def test_a_detail_is_known_by_its_own_word_and_the_words_also_taken_for_it(what, said):
    answer = _say(_with(fog_area_fraction=20.0), what=what, from_time="15")
    assert answer == f"Today at 15:00 in Testheim: {said}."


def test_a_time_between_six_hour_steps_takes_the_step_it_falls_in():
    """Beyond its hours MET steps six hours at a time: 08:00 on Monday is in the 06:00 step."""
    said = _say(
        FakeApi(complete=detailed(_plain, hours=12, far=8)), what="humidity", day="mandag", from_time="8"
    )
    assert said == "Monday at 08:00 in Testheim: humidity 66 percent."


def test_fog_over_hours_is_its_most_likely():
    def morning(local):
        return _plain(local) | {"fog_area_fraction": 70.0 if local.hour == 15 else 0.0}

    said = _say(FakeApi(complete=detailed(morning)), what="fog", from_time="14", to_time="18")
    assert said.endswith(": fog likely.")


@pytest.mark.parametrize(
    ("degrees", "said"),
    [
        (0.0, "the north"),
        (22.0, "the north"),
        (23.0, "the north-east"),
        (90.0, "the east"),
        (135.0, "the south-east"),
        (180.0, "the south"),
        (225.0, "the south-west"),
        (270.0, "the west"),
        (315.0, "the north-west"),
        (350.0, "the north"),
    ],
)
def test_the_wind_comes_from_where_met_says_in_eight_points(degrees, said):
    """wind_from_direction is where the wind blows from; eight points are easy to hear."""
    answer = _say(_with(wind_from_direction=degrees), what="wind", from_time="15")
    assert answer.endswith(f": wind 3 metres a second from {said}, gusts to 7.")


def test_wind_over_hours_is_its_strongest_hour():
    def gale(local):
        if local.hour == 16:
            return _plain(local) | {
                "wind_speed": 9.4,
                "wind_speed_of_gust": 14.2,
                "wind_from_direction": 270.0,
            }
        return _plain(local)

    said = _say(FakeApi(complete=detailed(gale)), what="wind", from_time="14", to_time="18")
    assert said.endswith(": wind up to 9 metres a second from the west, gusts to 14.")


def test_wind_with_no_gust_from_met_says_none():
    said = _say(FakeApi(complete=detailed(_plain, hours=12, far=8)), what="wind", day="mandag")
    assert said.startswith("Monday in Testheim: wind up to 3 metres a second from the south-west")
    assert "gust" not in said


def test_a_detail_met_does_not_give_that_far_ahead_says_so():
    answer = _detail(FakeApi(complete=detailed(_plain, hours=12, far=8)), what="uv", day="mandag")
    assert answer == {
        "success": False,
        "say": "MET gives no UV index that far ahead. Ask for a time in the next two days.",
    }


def test_an_unknown_detail_lists_the_words():
    answer = _detail(what="pollen")
    assert answer == {"success": False, "say": "Which detail? Say uv, humidity, dew point, fog or wind."}


def test_a_detail_past_the_forecast_says_how_far_it_reaches():
    answer = _detail(
        FakeApi(complete=detailed(_plain, hours=12)), what="humidity", day="tomorrow", from_time="15"
    )
    assert answer == {"success": False, "say": "MET's forecast reaches to Tomorrow at 01:00."}


def test_the_details_come_from_the_complete_forecast():
    """Only this tool reads MET's complete forecast; the others keep compact's one request."""
    api = FakeApi(complete=detailed(_plain))
    voice = Voice(api)
    try:
        voice.loop.run_until_complete(voice.server.call_tool("weather_detail", {"what": "fog"}))
        voice.now()
    finally:
        voice.close()
    assert [r.url.path for r in api.requests if "locationforecast" in r.url.path] == [
        COMPLETE_PATH,
        FORECAST_PATH,
    ]


def test_weather_detail_only_reads():
    voice = Voice()
    try:
        tool = voice.tools()["weather_detail"]
    finally:
        voice.close()
    assert tool.annotations.read_only_hint is True
    for word in ("uv", "humidity", "dew point", "fog", "wind"):
        assert word in tool.description.lower()

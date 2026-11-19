"""weather_detail's sun and moon, from MET's sunrise 3.0 answers, through the MCP server.

The fake's clock is 13:00 in Oslo on Saturday 14 November 2026.
"""

import pytest
from fakes import MOON_PATH, SUN_PATH, FakeApi, moon, sun
from test_weather_now import Voice


def _detail(api=None, **asked):
    voice = Voice(api or FakeApi())
    try:
        result = voice.loop.run_until_complete(voice.server.call_tool("weather_detail", asked))
        return result.structured_content, voice.api
    finally:
        voice.close()


def _say(api=None, **asked):
    answer, _ = _detail(api, **asked)
    assert answer["success"], answer
    return answer["say"]


def test_sunrise_and_sunset_come_from_mets_sun_answer():
    assert _say(what="sunrise") == "Today in Testheim: sunrise at 08:24."
    assert _say(what="sunset") == "Today in Testheim: sunset at 15:40."
    assert _say(what="sun") == "Today in Testheim: sunrise at 08:24, sunset at 15:40."


def test_the_polar_night_says_the_sun_does_not_rise():
    api = FakeApi(sun=sun(None, None, noon_visible=False))
    assert _say(api, what="sunset") == "Today in Testheim: the sun does not rise."


def test_the_midnight_sun_says_the_sun_does_not_set():
    api = FakeApi(sun=sun(None, None, midnight_visible=True))
    assert _say(api, what="sunrise") == "Today in Testheim: the sun does not set."


def test_a_day_the_sun_only_rises_says_no_sunset():
    """Near the polar night's end the sun can rise and not set by midnight, or the other way."""
    assert (
        _say(FakeApi(sun=sun("11:50", None)), what="sun") == "Today in Testheim: sunrise at 11:50, no sunset."
    )


@pytest.mark.parametrize(
    ("degrees", "phase"),
    [
        (0.0, "new"),
        (11.9, "new"),
        (12.0, "waxing crescent"),
        (78.0, "first quarter"),
        (101.9, "first quarter"),
        (102.0, "waxing gibbous"),
        (168.0, "full"),
        (191.9, "full"),
        (192.0, "waning gibbous"),
        (258.0, "last quarter"),
        (282.0, "waning crescent"),
        (348.0, "new"),
        (359.9, "new"),
    ],
)
def test_the_moon_phase_is_said_in_plain_words(degrees, phase):
    """New and full within 12 degrees, about a day; the quarters too; crescent and gibbous between."""
    said = _say(FakeApi(moon=moon(degrees)), what="moon")
    assert said == f"Today in Testheim: the moon is {phase}."


def test_moonrise_and_moonset_come_from_mets_moon_answer():
    assert _say(what="moonrise") == "Today in Testheim: moonrise at 13:57."
    assert _say(what="moonset") == "Today in Testheim: moonset at 00:47."


def test_a_day_with_no_moonrise_says_so():
    assert _say(FakeApi(moon=moon(rise=None)), what="moonrise") == "Today in Testheim: no moonrise."


def test_sun_and_moon_are_asked_for_the_day_asked_about():
    """The date and the place's offset that day go to MET; a time asked about changes nothing."""
    answer, api = _detail(what="sunset", day="fredag", from_time="15")
    assert answer["say"] == "Friday in Testheim: sunset at 15:40."
    asked = next(r for r in api.requests if r.url.path == SUN_PATH)
    assert asked.url.params["date"] == "2026-11-20"
    assert asked.url.params["offset"] == "+01:00"


def test_summer_is_asked_with_summer_time():
    _, api = _detail(what="moon", day="20.06")
    asked = next(r for r in api.requests if r.url.path == MOON_PATH)
    assert asked.url.params["date"] == "2027-06-20"
    assert asked.url.params["offset"] == "+02:00"


def test_sun_or_moon_on_a_day_gone_is_refused():
    answer, _ = _detail(what="sunrise", day="13.11")
    assert answer["success"] is False


def test_the_detail_words_name_the_sun_and_moon():
    answer, _ = _detail(what="pollen")
    words = "uv, humidity, dew point, fog, wind, sunrise, sunset, sun, moon, moonrise or moonset"
    assert answer["say"] == f"Which detail? Say {words}."

"""Every weather symbol MET can send gets spoken words.

The codes are MET's published list (github.com/metno/weathericons, read
2026-11-15), without their _day, _night or _polartwilight ending. Two of them
are misspelled there, and MET sends them so.
"""

import pytest

from weather_mcp.weather import sky_words

CODES = [
    "clearsky",
    "cloudy",
    "fair",
    "fog",
    "partlycloudy",
    "heavyrain",
    "heavyrainandthunder",
    "heavyrainshowers",
    "heavyrainshowersandthunder",
    "heavysleet",
    "heavysleetandthunder",
    "heavysleetshowers",
    "heavysleetshowersandthunder",
    "heavysnow",
    "heavysnowandthunder",
    "heavysnowshowers",
    "heavysnowshowersandthunder",
    "lightrain",
    "lightrainandthunder",
    "lightrainshowers",
    "lightrainshowersandthunder",
    "lightsleet",
    "lightsleetandthunder",
    "lightsleetshowers",
    "lightssleetshowersandthunder",
    "lightsnow",
    "lightsnowandthunder",
    "lightsnowshowers",
    "lightssnowshowersandthunder",
    "rain",
    "rainandthunder",
    "rainshowers",
    "rainshowersandthunder",
    "sleet",
    "sleetandthunder",
    "sleetshowers",
    "sleetshowersandthunder",
    "snow",
    "snowandthunder",
    "snowshowers",
    "snowshowersandthunder",
]


@pytest.mark.parametrize("code", CODES)
def test_every_symbol_has_words(code):
    assert sky_words(code + "_day")


@pytest.mark.parametrize(
    ("code", "words"),
    [
        ("clearsky_night", "clear"),
        ("partlycloudy_polartwilight", "partly cloudy"),
        ("heavysleetshowersandthunder_day", "heavy sleet showers and thunder"),
        ("lightssnowshowersandthunder_night", "light snow showers and thunder"),
        ("rainandthunder", "rain and thunder"),
    ],
)
def test_a_symbol_reads_as_words(code, words):
    assert sky_words(code) == words


def test_an_unknown_symbol_has_no_words():
    assert sky_words("somethingnew_day") == ""

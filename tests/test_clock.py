"""Clock times as the owner says them, in Norwegian or English, and the Oslo hour they mean."""

import datetime as dt

import pytest

from weather_mcp.clock import OSLO, at_hour, which_hour


@pytest.mark.parametrize(
    ("said", "hour"),
    [
        ("15", 15),
        ("15:00", 15),
        ("15.00", 15),
        ("kl 15", 15),
        ("kl. 15", 15),
        ("Klokka 15", 15),
        ("klokken 15.00", 15),
        ("at 15", 15),
        ("15:30", 15),
        ("15?", 15),
        ("0", 0),
        ("08", 8),
    ],
)
def test_an_hour_is_read_as_said(said, hour):
    assert which_hour(said) == hour


def test_a_bare_hour_is_read_on_a_twenty_four_hour_clock():
    """Three is three at night; the answer says "03:00" back, so a misreading is heard at once."""
    assert which_hour("3") == 3


@pytest.mark.parametrize(
    ("said", "hour"),
    [("3 pm", 15), ("3pm", 15), ("3 p.m.", 15), ("12 am", 0), ("12 pm", 12), ("9 am", 9)],
)
def test_am_and_pm_hours_are_read_on_a_twelve_hour_clock(said, hour):
    assert which_hour(said) == hour


@pytest.mark.parametrize("said", ["24", "25", "99"])
def test_an_hour_past_the_last_of_the_day_means_none(said):
    assert which_hour(said) is None


@pytest.mark.parametrize("said", ["soon", "", "fifteen", "15 16", "kl"])
def test_words_that_name_no_hour_mean_none(said):
    assert which_hour(said) is None


def test_an_hour_said_twice_in_autumn_means_the_first():
    """On 25.10.2026 the clocks go back at 03:00, so 02:00 comes twice; summer time's is first."""
    first = at_hour(dt.date(2026, 10, 25), 2)
    assert first.hour == 2
    assert first.utcoffset() == dt.timedelta(hours=2)


def test_an_hour_skipped_in_spring_means_the_next():
    """On 29.03.2026 the clocks go forward at 02:00, so there is no 02:00; 03:00 comes instead."""
    skipped = at_hour(dt.date(2026, 3, 29), 2)
    assert (skipped.hour, skipped.utcoffset()) == (3, dt.timedelta(hours=2))


def test_an_ordinary_hour_is_that_hour_in_oslo():
    at = at_hour(dt.date(2026, 11, 20), 15)
    assert at == dt.datetime(2026, 11, 20, 14, tzinfo=dt.UTC)
    assert at.tzinfo == OSLO


@pytest.mark.parametrize("said", ["13 pm", "0 am", "20 pm"])
def test_a_twelve_hour_clock_has_no_hour_past_twelve(said):
    assert which_hour(said) is None


@pytest.mark.parametrize("said", ["15:60", "15:75", "15.99"])
def test_an_hour_has_no_more_than_sixty_minutes(said):
    assert which_hour(said) is None

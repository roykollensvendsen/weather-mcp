"""Which day a spoken word means, worked out by the plugin in Oslo time, never by the voice model.

"Today" here is Saturday 14 November 2026.
"""

import datetime as dt

import pytest

from weather_mcp.days import label, which_day

TODAY = dt.date(2026, 11, 14)  # a Saturday
NOV = {d: dt.date(2026, 11, d) for d in range(14, 30)}


@pytest.mark.parametrize(
    ("said", "meant"),
    [
        ("today", NOV[14]),
        ("i dag", NOV[14]),
        (" I DAG ", NOV[14]),
        ("tomorrow", NOV[15]),
        ("i morgen", NOV[15]),
        ("imorgen", NOV[15]),
        ("the day after tomorrow", NOV[16]),
        ("i overmorgen", NOV[16]),
        ("overmorgen", NOV[16]),
        ("sunday", NOV[15]),
        ("søndag", NOV[15]),
        ("på søndag", NOV[15]),
        ("on Sunday", NOV[15]),
        ("this sunday", NOV[15]),
        ("sondag", NOV[15]),
        ("Monday", NOV[16]),
        ("mandag", NOV[16]),
        ("tirsdag", NOV[17]),
        ("onsdag", NOV[18]),
        ("torsdag", NOV[19]),
        ("fredag", NOV[20]),
        ("Friday", NOV[20]),
        ("på fredag", NOV[20]),
        ("next friday", NOV[20]),
        ("neste fredag", NOV[20]),
        ("2026-11-20", NOV[20]),
        ("20.11", NOV[20]),
        ("20.11.", NOV[20]),
        ("20.11.2026", NOV[20]),
    ],
)
def test_a_spoken_day_means_one_date(said, meant):
    assert which_day(said, TODAY) == meant


def test_a_weekday_said_on_that_day_is_today():
    """Lørdag said on a Saturday is that day, not a week on."""
    assert which_day("lørdag", TODAY) == NOV[14]
    assert which_day("saturday", TODAY) == NOV[14]
    assert which_day("lordag", TODAY) == NOV[14]


def test_next_with_a_weekday_skips_today():
    assert which_day("neste lørdag", TODAY) == NOV[21]
    assert which_day("next saturday", TODAY) == NOV[21]


def test_a_date_long_past_this_year_means_next_year():
    """Said in November, "1.1" is New Year's Day to come; a date just gone is still this year's."""
    assert which_day("1.1", TODAY) == dt.date(2027, 1, 1)
    assert which_day("10.11", TODAY) == dt.date(2026, 11, 10)


@pytest.mark.parametrize(
    "said", ["", "someday", "fredag morgen kveld", "31.02", "2026-13-01", "next", "neste"]
)
def test_a_word_that_names_no_day_means_none(said):
    assert which_day(said, TODAY) is None


@pytest.mark.parametrize(
    ("day", "said"),
    [
        (NOV[14], "Today"),
        (NOV[15], "Tomorrow"),
        (NOV[16], "Monday"),
        (NOV[20], "Friday"),
        (NOV[21], "Saturday 21.11"),
        (NOV[23], "Monday 23.11"),
    ],
)
def test_a_day_is_said_by_its_name_and_by_its_date_once_a_week_away(day, said):
    """Within the week a weekday is enough; a week or more away, the same name needs its date."""
    assert label(day, TODAY) == said


@pytest.mark.parametrize("said", ["fredag?", "Friday.", "på fredag!", "fredag, ", "fredag?!"])
def test_trailing_punctuation_is_left_out(said):
    """A voice's text can end in a question mark or a full stop; the day is still the day."""
    assert which_day(said, TODAY) == NOV[20]

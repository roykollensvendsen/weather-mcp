"""Turning a spoken name into a point, through Kartverket's place names."""

import asyncio

import httpx
from fakes import PLACES_PATH, FakeApi

from weather_mcp.places import PlaceFinder


def find(name: str, api: FakeApi | None = None):
    api = api or FakeApi()

    async def go():
        async with httpx.AsyncClient(transport=api.transport()) as http:
            finder = PlaceFinder(http, "weather-mcp/0 https://example.org")
            return await finder.find(name)

    return asyncio.run(go())


def test_a_known_name_gives_its_point():
    found = find("Testby")
    assert found.place is not None
    assert found.place.name == "Testby"
    assert found.choices == []


def test_a_named_place_is_rounded_to_two_decimals():
    found = find("Testby")
    assert found.place is not None
    assert (found.place.lat, found.place.lon) == (61.0, 9.0)


def test_a_shared_name_asks_which_one():
    found = find("Moen")
    assert found.place is None
    assert found.choices == ["Fjellfylke", "Kystfylke", "Nordfylke"]


def test_only_settled_places_are_asked_for():
    found = find("Lia")
    assert found.place is not None
    assert (found.place.lat, found.place.lon) == (61.08, 9.08)


def test_a_name_with_i_in_it_is_found_whole():
    found = find("Strand i Dal")
    assert found.place is not None
    assert found.place.name == "Strand i Dal"


def test_a_county_named_in_one_of_its_languages_matches():
    found = find("Moen i Nordfylke")
    assert found.place is not None
    assert (found.place.lat, found.place.lon) == (61.06, 9.06)


def test_a_town_wins_over_a_farm_of_the_same_name():
    found = find("Haugen")
    assert found.place is not None
    assert (found.place.lat, found.place.lon) == (61.05, 9.05)


def test_a_county_picks_one_of_a_shared_name():
    found = find("Moen i Kystfylke")
    assert found.place is not None
    assert (found.place.lat, found.place.lon) == (61.02, 9.02)


def test_an_unknown_name_finds_nothing():
    found = find("Ingenstad")
    assert found.place is None
    assert found.choices == []


def test_a_name_is_looked_up_once():
    api = FakeApi()

    async def go():
        async with httpx.AsyncClient(transport=api.transport()) as http:
            finder = PlaceFinder(http, "weather-mcp/0 https://example.org")
            await finder.find("Testby")
            await finder.find("testby")

    asyncio.run(go())
    assert len([r for r in api.requests if r.url.path == PLACES_PATH]) == 1


def test_two_towns_of_one_name_in_one_county_are_asked_by_municipality():
    found = find("Bø")
    assert found.place is None
    assert found.choices == ["Nedreli", "Øvreli"]


def test_a_municipality_picks_one_of_two_towns_in_a_county():
    found = find("Bø i Nedreli")
    assert found.place is not None
    assert (found.place.lat, found.place.lon) == (61.12, 9.12)


def test_a_town_and_its_municipality_are_one_place():
    found = find("Testby")
    assert found.place is not None
    assert found.choices == []


def test_too_many_towns_are_narrowed_by_county_first():
    found = find("Moen i Fjellfylke")
    assert found.place is None
    assert found.choices == ["Fjellfylkevik", "Øvreli"]

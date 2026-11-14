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
    assert found.choices == ["Fjellfylke", "Kystfylke"]


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

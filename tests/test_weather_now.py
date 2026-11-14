"""weather_now, through the MCP server, against the fake MET and Kartverket.

Home here is made up, at 61.00 N 9.00 E.
"""

import asyncio

import httpx
from fakes import FakeApi, forecast

from weather_mcp.cache import CachedClient
from weather_mcp.config import Config, Place
from weather_mcp.places import PlaceFinder
from weather_mcp.server import build_server
from weather_mcp.weather import Weather

HOME = Place(name="Testheim", lat=61.0, lon=9.0)
AGENT = "weather-mcp/0 https://example.org"


class Voice:
    """Calls the server's tools as a voice session would, over one open client."""

    def __init__(self, api: FakeApi | None = None, home: Place | None = HOME):
        self.api = api or FakeApi()
        self.loop = asyncio.new_event_loop()
        self.http = httpx.AsyncClient(transport=self.api.transport())
        weather = Weather(
            Config(contact="https://example.org", home=home),
            CachedClient(self.http, AGENT, clock=self.api.clock),
            PlaceFinder(self.http, AGENT),
        )
        self.server = build_server(weather)

    def now(self, place: str | None = None) -> dict:
        arguments = {} if place is None else {"place": place}
        result = self.loop.run_until_complete(self.server.call_tool("weather_now", arguments))
        return result.structured_content

    def tools(self):
        return {t.name: t for t in self.loop.run_until_complete(self.server.list_tools())}

    def close(self):
        self.loop.run_until_complete(self.http.aclose())
        self.loop.close()


def ask(place: str | None = None, **kwargs) -> dict:
    voice = Voice(**kwargs)
    try:
        return voice.now(place)
    finally:
        voice.close()


def test_weather_now_at_home_says_the_temperature_and_the_sky():
    answer = ask()
    assert answer["success"]
    assert answer["say"] == "7 degrees and cloudy in Testheim."


def test_the_point_sent_to_met_has_two_decimals():
    api = FakeApi()
    ask(api=api)
    sent = api.forecast_requests()[0].url.params
    assert (sent["lat"], sent["lon"]) == ("61.00", "9.00")


def test_a_named_place_gives_its_weather():
    api = FakeApi()
    answer = ask("Testby", api=api)
    assert answer["say"] == "7 degrees and cloudy in Testby."
    sent = api.forecast_requests()[0].url.params
    assert (sent["lat"], sent["lon"]) == ("61.00", "9.00")


def test_a_shared_name_is_asked_back():
    answer = ask("Moen")
    assert not answer["success"]
    assert answer["say"] == "Which Moen: in Fjellfylke or Kystfylke?"


def test_an_unknown_place_says_only_norway_is_known():
    answer = ask("Ingenstad")
    assert not answer["success"]
    assert "only know places in Norway" in answer["say"]


def test_no_home_says_where_to_set_it():
    answer = ask(home=None)
    assert not answer["success"]
    assert "config.toml" in answer["say"]


def test_frost_is_said_as_minus():
    answer = ask(api=FakeApi(body=forecast(temperature=-3.4, symbol="lightsnow_night")))
    assert answer["say"] == "Minus 3 degrees and light snow in Testheim."


def test_one_degree_is_singular():
    answer = ask(api=FakeApi(body=forecast(temperature=1.2, symbol="clearsky_day")))
    assert answer["say"] == "1 degree and clear in Testheim."


def test_a_slowed_answer_says_how_old_it_is():
    voice = Voice()
    try:
        voice.now()
        voice.api.clock.advance(31)
        voice.api.slow_down = True
        answer = voice.now()
    finally:
        voice.close()
    assert answer["success"]
    assert answer["say"] == (
        "7 degrees and cloudy in Testheim. The forecast is from 13:00; MET asked us to slow down."
    )


def test_met_not_answering_says_what_to_do_next():
    answer = ask(api=FakeApi(broken=500))
    assert not answer["success"]
    assert answer["say"] == "MET isn't answering. Yr's app still works."


def test_weather_now_only_looks():
    tool = Voice().tools()["weather_now"]
    assert tool.annotations.read_only_hint


def test_the_tool_credits_met_norway():
    tool = Voice().tools()["weather_now"]
    assert "Data from MET Norway" in tool.description

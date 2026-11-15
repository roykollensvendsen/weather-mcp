"""weather_now, through the MCP server, against the fake MET and Kartverket.

Home here is made up, at 61.00 N 9.00 E.
"""

import asyncio
import logging

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

    def __init__(self, api: FakeApi | None = None, home: Place | None = HOME, answer_within: float = 12.0):
        self.api = api or FakeApi()
        self.loop = asyncio.new_event_loop()
        self.http = httpx.AsyncClient(transport=self.api.transport())
        weather = Weather(
            Config(contact="https://example.org", home=home),
            CachedClient(self.http, AGENT, clock=self.api.clock),
            PlaceFinder(self.http, AGENT),
        )
        self.server = build_server(weather, answer_within=answer_within)

    def now(self, place: str | None = None, **position) -> dict:
        arguments = ({} if place is None else {"place": place}) | position
        result = self.loop.run_until_complete(self.server.call_tool("weather_now", arguments))
        return result.structured_content

    def forecast(self, **asked) -> dict:
        result = self.loop.run_until_complete(self.server.call_tool("weather_forecast", asked))
        return result.structured_content

    def tools(self):
        return {t.name: t for t in self.loop.run_until_complete(self.server.list_tools())}

    def close(self):
        self.loop.run_until_complete(self.http.aclose())
        self.loop.close()


def ask(place: str | None = None, position=None, **kwargs) -> dict:
    voice = Voice(**kwargs)
    try:
        return voice.now(place, **(position or {}))
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
    assert answer["say"] == "Which Moen: in Fjellfylke, Kystfylke or Nordfylke?"


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


def test_a_failure_logs_no_coordinates(caplog):
    caplog.set_level("DEBUG")
    answer = ask(api=FakeApi(crash=True))
    assert not answer["success"]
    logged = caplog.text
    assert "weather_now failed" in logged
    assert "61.00" not in logged
    assert "lat=" not in logged


def test_every_answer_comes_within_the_deadline():
    answer = ask(api=FakeApi(delay=0.5), answer_within=0.1)
    assert not answer["success"]
    assert answer["say"] == "MET is slow to answer just now. Ask again in a moment."


def test_a_refusal_names_the_contact_setting():
    answer = ask(api=FakeApi(broken=403))
    assert not answer["success"]
    assert answer["say"].startswith("MET refused the request.")
    assert "contact" in answer["say"]


def test_an_echoed_place_is_one_short_line():
    answer = ask("Ingen\nstad " + "x" * 200)
    assert "\n" not in answer["say"]
    assert len(answer["say"]) < 160


# A made-up phone position, away from home and every made-up place, more exact than MET takes.
PHONE = {"lat": 61.3712, "lon": 9.4249, "accuracy_m": 30.0}


def _asked(voice):
    return [dict(r.url.params) for r in voice.api.forecast_requests()]


def test_a_position_answers_for_where_the_phone_is():
    voice = Voice()
    try:
        answer = voice.now(**PHONE)
        assert answer["success"]
        assert answer["say"] == "7 degrees and cloudy where you are."
    finally:
        voice.close()


def test_a_position_is_rounded_to_two_decimals_before_it_is_used():
    """MET's terms, and a point rounded to about a kilometre says less about the owner."""
    voice = Voice()
    try:
        voice.now(**PHONE)
        assert _asked(voice) == [{"lat": "61.37", "lon": "9.42"}]
    finally:
        voice.close()


def test_a_named_place_comes_before_the_position():
    voice = Voice()
    try:
        assert voice.now("Haugen", **PHONE)["say"].endswith("in Haugen.")
        assert {"lat": "61.37", "lon": "9.42"} not in _asked(voice)
    finally:
        voice.close()


def test_half_a_position_is_said_and_never_taken_for_home():
    """'Here' answered for home would be wrong without saying so; MET is not asked."""
    voice = Voice()
    try:
        answer = voice.now(lat=61.3712)
        assert not answer["success"]
        assert "position" in answer["say"]
        assert voice.api.forecast_requests() == []
    finally:
        voice.close()


def test_with_no_position_home_is_the_fallback():
    assert ask()["say"] == "7 degrees and cloudy in Testheim."


def test_a_position_needs_no_home():
    assert ask(position=PHONE, home=None)["success"]


def test_a_position_that_is_not_on_earth_is_said_and_never_sent():
    voice = Voice()
    try:
        answer = voice.now(lat=95.0, lon=9.0)
        assert not answer["success"]
        assert "position" in answer["say"]
        assert voice.api.forecast_requests() == []
    finally:
        voice.close()


def test_a_rough_position_is_said_to_be_rough():
    answer = ask(position={**PHONE, "accuracy_m": 25_000.0})
    assert (
        answer["say"]
        == "7 degrees and cloudy where you are. The phone's position is rough, so this may be off."
    )


def test_a_position_is_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    ask(position=PHONE)
    assert "61.37" not in caplog.text
    assert "9.42" not in caplog.text


def test_the_tool_asks_the_voice_for_the_phones_position():
    voice = Voice()
    try:
        tool = voice.tools()["weather_now"]
        assert {"place", "lat", "lon", "accuracy_m"} <= set(tool.input_schema["properties"])
        assert "phone's position" in tool.description
    finally:
        voice.close()


def test_a_failed_request_carries_the_position_nowhere(caplog):
    """The errors httpx raises carry the whole request, and its address holds the position."""
    caplog.set_level(logging.DEBUG)
    voice = Voice(FakeApi(refuse_connection=True))
    try:
        answer = voice.now(**PHONE)
    finally:
        voice.close()
    assert not answer["success"]
    for seen in (caplog.text, str(answer)):
        assert "61.37" not in seen
        assert "9.42" not in seen


def test_a_position_is_never_logged_by_httpcores_own_loggers(caplog):
    """A filter on a logger misses what its children log, and httpcore logs on its children."""
    caplog.set_level(logging.DEBUG)
    Voice().close()
    for child in ("httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
        logging.getLogger(child).debug("asked https://api.met.no/forecast?lat=61.37&lon=9.42")
    assert "61.37" not in caplog.text
    assert "asked https://api.met.no/forecast?…" in caplog.text


def test_building_many_servers_keeps_one_filter():
    Voice().close()
    Voice().close()
    assert len(logging.getLogger("httpcore.http11").filters) == 1

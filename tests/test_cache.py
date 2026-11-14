"""The cache MET's terms ask every client to be."""

import asyncio

import httpx
import pytest
from fakes import FORECAST_PATH, LAST_MODIFIED, FakeApi

from weather_mcp.cache import CachedClient, SlowedDownError, UpstreamError

URL = "https://api.met.no" + FORECAST_PATH
POINT = {"lat": "61.0", "lon": "9.0"}


def fetch(api: FakeApi, params=None):
    """One ask from a new client, as a first request after start is."""

    async def fresh():
        async with httpx.AsyncClient(transport=api.transport()) as http:
            client = CachedClient(http, "weather-mcp/0 https://example.org", clock=api.clock)
            return await client.get_json(URL, params or POINT)

    return asyncio.run(fresh())


class Session:
    """One client kept open across several asks, as the server keeps it."""

    def __init__(self, api: FakeApi):
        self.api = api
        self.loop = asyncio.new_event_loop()
        self.http = httpx.AsyncClient(transport=api.transport())
        self.client = CachedClient(self.http, "weather-mcp/0 https://example.org", clock=api.clock)

    def ask(self):
        return self.loop.run_until_complete(self.client.get_json(URL, POINT))

    def close(self):
        self.loop.run_until_complete(self.http.aclose())
        self.loop.close()


@pytest.fixture
def session():
    s = Session(FakeApi())
    yield s
    s.close()


def test_every_request_says_who_is_asking():
    api = FakeApi()
    answer = fetch(api)
    assert answer.data["type"] == "Feature"
    assert api.requests[0].headers["user-agent"] == "weather-mcp/0 https://example.org"


def test_nothing_is_asked_again_before_it_expires(session):
    session.ask()
    session.api.clock.advance(29)
    answer = session.ask()
    assert len(session.api.forecast_requests()) == 1
    assert answer.data["type"] == "Feature"


def test_a_repeat_after_expiry_asks_with_if_modified_since(session):
    session.ask()
    session.api.clock.advance(31)
    answer = session.ask()
    asked = session.api.forecast_requests()
    assert len(asked) == 2
    assert asked[1].headers["if-modified-since"] == LAST_MODIFIED
    assert answer.data["type"] == "Feature", "a 304 still answers from what was kept"


def test_a_304_moves_the_expiry_on(session):
    session.ask()
    session.api.clock.advance(31)
    session.ask()
    session.api.clock.advance(29)
    session.ask()
    assert len(session.api.forecast_requests()) == 2


def test_a_429_answers_from_the_cache(session):
    first = session.ask()
    session.api.clock.advance(31)
    session.api.slow_down = True
    answer = session.ask()
    assert answer.slowed
    assert answer.data == first.data
    assert answer.fetched == first.fetched


def test_a_429_holds_off_before_asking_again(session):
    session.ask()
    session.api.clock.advance(31)
    session.api.slow_down = True
    session.ask()
    session.ask()
    assert len(session.api.forecast_requests()) == 2


def test_a_429_with_nothing_kept_says_so():
    api = FakeApi(slow_down=True)
    with pytest.raises(SlowedDownError):
        fetch(api)


def test_a_refusal_is_an_upstream_error():
    api = FakeApi()
    with pytest.raises(UpstreamError) as caught:
        fetch(api, params={"lat": "61.00001", "lon": "9.0"})
    assert caught.value.status == 403

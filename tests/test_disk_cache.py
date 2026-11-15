"""The cache survives a restart, so MET is never asked again before Expires.

Each "restart" here is a new client over the same file, as a new server
process would be.
"""

import asyncio
import json
import stat

import httpx
import pytest
from fakes import FORECAST_PATH, LAST_MODIFIED, FakeApi

from weather_mcp.cache import CachedClient, SlowedDownError, cache_path

URL = "https://api.met.no" + FORECAST_PATH
POINT = {"lat": "61.00", "lon": "9.00"}
AGENT = "weather-mcp/0 https://example.org"


def ask(api: FakeApi, store, point=POINT):
    """One ask from a newly started client, over the cache file given."""

    async def go():
        async with httpx.AsyncClient(transport=api.transport()) as http:
            return await CachedClient(http, AGENT, clock=api.clock, store=store).get_json(URL, point)

    return asyncio.run(go())


def test_a_restart_keeps_what_the_cache_held(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    ask(api, store)
    api.clock.advance(29)
    answer = ask(api, store)
    assert len(api.forecast_requests()) == 1, "a restart must not ask MET before Expires"
    assert answer.data["type"] == "Feature"


def test_a_restart_asks_with_if_modified_since_after_expiry(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    ask(api, store)
    api.clock.advance(31)
    ask(api, store)
    assert api.forecast_requests()[1].headers["if-modified-since"] == LAST_MODIFIED


def test_a_restart_keeps_the_hold_off(tmp_path):
    api, store = FakeApi(slow_down=True), tmp_path / "forecasts.json"
    with pytest.raises(SlowedDownError):
        ask(api, store)
    with pytest.raises(SlowedDownError):
        ask(api, store)
    assert len(api.forecast_requests()) == 1


def test_a_damaged_cache_file_is_ignored(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    store.write_text("{not json")
    assert ask(api, store).data["type"] == "Feature"
    assert json.loads(store.read_text()), "the file is written fresh"


def test_the_cache_file_is_private(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    ask(api, store)
    assert stat.S_IMODE(store.stat().st_mode) == 0o600


def test_the_cache_lives_under_the_users_cache_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache_path() == tmp_path / "weather-mcp" / "forecasts.json"

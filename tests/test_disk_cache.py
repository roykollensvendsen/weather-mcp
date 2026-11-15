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


def ask(api: FakeApi, store, point=POINT, keep=()):
    """One ask from a newly started client, over the cache file given."""

    async def go():
        async with httpx.AsyncClient(transport=api.transport()) as http:
            client = CachedClient(http, AGENT, clock=api.clock, store=store, keep=keep)
            return await client.get_json(URL, point)

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


def test_a_failed_save_never_stops_an_answer(tmp_path, caplog):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        answer = ask(FakeApi(), locked / "forecasts.json")
    finally:
        locked.chmod(0o700)
    assert answer.data["type"] == "Feature"
    assert "PermissionError" in caplog.text
    assert "is writable" in caplog.text
    assert "61.00" not in caplog.text


def test_a_cache_that_cannot_be_read_starts_afresh(tmp_path, caplog):
    store = tmp_path / "forecasts.json"
    store.write_text("{}")
    store.chmod(0o000)
    try:
        answer = ask(FakeApi(), store)
    finally:
        store.chmod(0o600)
    assert answer.data["type"] == "Feature"
    assert "could not read the forecast cache (PermissionError)" in caplog.text


def _stored(store, held_until, expires="2026-11-14T12:30:00+00:00"):
    body = {
        "held_until": held_until,
        "kept": {
            URL + "?lat=61.00&lon=9.00": {
                "data": {"type": "Kept"},
                "fetched": "2026-11-14T11:00:00+00:00",
                "expires": expires,
                "last_modified": None,
            }
        },
    }
    store.write_text(json.dumps(body))


def test_a_stored_time_with_no_zone_is_damage(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    _stored(store, None, expires="2026-11-14T12:30:00")
    assert ask(api, store).data["type"] == "Feature", "the damaged file is not trusted"
    assert len(api.forecast_requests()) == 1


def test_a_stored_pause_is_at_most_an_hour(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    _stored(store, "2026-12-14T12:00:00+00:00", expires="2026-11-14T11:30:00+00:00")
    assert ask(api, store).slowed, "the pause still holds at first"
    api.clock.advance(61)
    assert ask(api, store).data["type"] == "Feature", "but a restart an hour later asks again"
    assert len(api.forecast_requests()) == 1


OTHER = {"lat": "61.50", "lon": "9.50"}


def test_places_expired_over_a_day_ago_are_forgotten(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    ask(api, store, OTHER)
    api.clock.advance(25 * 60 + 31)
    ask(api, store, POINT)
    assert "lat=61.50" not in store.read_text(), "the file must not become a history of places"
    assert "lat=61.00" in store.read_text()


def test_home_is_never_forgotten(tmp_path):
    api, store = FakeApi(), tmp_path / "forecasts.json"
    ask(api, store, OTHER, keep=[OTHER])
    api.clock.advance(25 * 60 + 31)
    ask(api, store, POINT, keep=[OTHER])
    assert "lat=61.50" in store.read_text()


def test_the_cache_folder_is_private(tmp_path):
    api, store = FakeApi(), tmp_path / "weather-mcp" / "forecasts.json"
    ask(api, store)
    assert stat.S_IMODE(store.parent.stat().st_mode) == 0o700

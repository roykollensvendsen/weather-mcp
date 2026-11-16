"""weather-mcp serve --simulate: made-up weather, no network, and every answer says so."""

import asyncio
import socket

import pytest

from weather_mcp import cli


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to reach a real service fails the test."""

    def refuse(*_args, **_kwargs):
        msg = "a simulated run tried the network"
        raise AssertionError(msg)

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("weather_now", {}),
        ("weather_now", {"place": "Testheim"}),
        ("weather_now", {"lat": 61.0, "lon": 9.0}),
        ("weather_now", {"place": "Nowhere at all"}),
        ("weather_forecast", {}),
        ("weather_forecast", {"day": "today"}),
    ],
)
def test_every_simulated_answer_says_simulated_first(tool, arguments):
    from weather_mcp.simulated import simulated_server  # noqa: PLC0415

    async def go():
        async with simulated_server() as server:
            result = await server.call_tool(tool, arguments)
            return result.structured_content

    answer = asyncio.run(go())
    assert answer["say"].startswith("Simulated: ")


def test_a_simulated_run_never_touches_the_network():
    """The fixture above refuses any socket; a real sentence still comes back."""
    test_a_simulated_run_gives_real_sentences()


def test_a_simulated_run_gives_real_sentences():
    from weather_mcp.simulated import simulated_server  # noqa: PLC0415

    async def go():
        async with simulated_server() as server:
            now = await server.call_tool("weather_now", {})
            tomorrow = await server.call_tool("weather_forecast", {})
            return now.structured_content, tomorrow.structured_content

    now, tomorrow = asyncio.run(go())
    assert now["success"]
    assert " degrees" in now["say"]
    assert tomorrow["success"]
    assert tomorrow["say"].startswith("Simulated: Tomorrow in ")


def test_a_simulated_server_names_itself_simulated():
    from weather_mcp.simulated import simulated_server  # noqa: PLC0415

    async def go():
        async with simulated_server() as server:
            return server.name, server.instructions

    name, instructions = asyncio.run(go())
    assert name == "weather-simulated"
    assert instructions.startswith("SIMULATED:")


def test_serve_simulate_needs_no_config(monkeypatch, tmp_path):
    started = []

    async def fake_serve():
        started.append(True)

    monkeypatch.setattr(cli, "_serve_simulated", fake_serve)
    assert cli.main(["serve", "--simulate", "--config", str(tmp_path / "missing.toml")]) == 0
    assert started == [True]


def test_a_simulated_run_says_it_ignores_a_config_file(monkeypatch, tmp_path, capsys):
    """Asked for a config and for made-up weather, the run says which one it took."""

    async def fake_serve():
        return None

    monkeypatch.setattr(cli, "_serve_simulated", fake_serve)
    assert cli.main(["serve", "--simulate", "--config", str(tmp_path / "config.toml")]) == 0
    said = capsys.readouterr().err
    assert "--config is ignored" in said
    assert cli.main(["serve", "--simulate"]) == 0
    assert capsys.readouterr().err == ""

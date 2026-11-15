"""Command line for weather-mcp."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import pathlib
import sys

from weather_mcp.config import Config, ConfigError, config_path, load_config

#: Every verb this command has. The documentation test requires each one to
#: appear in a worked example, so a verb cannot be added without one.
COMMANDS: tuple[str, ...] = ("serve",)


def user_agent(config: Config) -> str:
    """What MET sees asking: this program, its version, and the owner's contact."""
    return f"weather-mcp/{importlib.metadata.version('weather-mcp')} {config.contact}"


async def _serve(config: Config) -> None:  # pragma: no cover - runs until stdin closes
    import httpx  # noqa: PLC0415 - only serving needs the network and the MCP server

    from weather_mcp.cache import CachedClient, cache_path  # noqa: PLC0415
    from weather_mcp.places import PlaceFinder  # noqa: PLC0415
    from weather_mcp.server import build_server  # noqa: PLC0415
    from weather_mcp.weather import Weather, point  # noqa: PLC0415

    agent = user_agent(config)
    # Two requests in a row for a named place, each well inside the voice's deadline.
    async with httpx.AsyncClient(timeout=5) as http:
        home = [point(config.home)] if config.home else []
        cache = CachedClient(http, agent, store=cache_path(), keep=home)
        weather = Weather(config, cache, PlaceFinder(http, agent))
        await build_server(weather).run_stdio_async()


async def _serve_simulated() -> None:  # pragma: no cover - runs until stdin closes
    from weather_mcp.simulated import simulated_server  # noqa: PLC0415

    async with simulated_server() as server:
        await server.run_stdio_async()


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="weather-mcp", description="The weather in Norway, by voice.")
    verbs = parser.add_subparsers(dest="command", metavar="command")
    serve = verbs.add_parser("serve", help="serve the weather tools over stdio")
    serve.add_argument("--config", metavar="FILE", help="the config file, if not the usual one")
    serve.add_argument(
        "--simulate", action="store_true", help="use made-up weather and places; touches no network"
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.simulate:
        asyncio.run(_serve_simulated())
        return 0
    return _serve_real(args.config)


def _serve_real(given: str | None) -> int:
    """Serve with the owner's config, or say why it can't be read."""
    path = pathlib.Path(given).expanduser() if given else config_path()
    try:
        config = load_config(path)
    except ConfigError as refused:
        sys.stderr.write(f"weather-mcp: {refused}\n")
        return 2
    asyncio.run(_serve(config))  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())

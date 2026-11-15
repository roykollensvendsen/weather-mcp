"""The local config: the contact MET requires, and where home is.

Home lives only in the owner's own file. It is rounded to two decimals, about
a kilometre, so the point sent to MET never names the house.
"""

from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass

#: Two decimals is about 1 km. MET's grid is coarser, so nothing is lost.
DECIMALS = 2

EXAMPLE = (
    'contact = "https://github.com/<you>/weather-mcp"\n'
    "[home]\n"
    'name = "<the name you say>"\n'
    "lat = 0.00\n"
    "lon = 0.00\n"
)


class ConfigError(Exception):
    """The config is missing or wrong; the message says what to write."""


@dataclass(frozen=True)
class Place:
    """A named point, already rounded."""

    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Config:
    """What the server needs before its first request."""

    contact: str
    home: Place | None


def config_path() -> pathlib.Path:
    """Where the config is read from, under the user's config folder."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(pathlib.Path.home() / ".config")
    return pathlib.Path(base) / "weather-mcp" / "config.toml"


def rounded(value: float) -> float:
    """A coordinate cut to the precision this plugin ever sends."""
    # RULE: home is rounded to two decimals
    return round(value, DECIMALS)


def load_config(path: pathlib.Path) -> Config:
    """Read the config, refusing one MET would refuse us for."""
    if not path.is_file():
        msg = f"No config at {path}. Write one like this:\n{EXAMPLE}"
        raise ConfigError(msg)
    with path.open("rb") as file:  # TOML is UTF-8 by its own spec, whatever the locale says
        raw = tomllib.load(file)
    contact = str(raw.get("contact") or "").strip()
    # RULE: the contact has no default
    if not contact:
        msg = f"{path} needs a contact: MET refuses requests that do not say who is asking."
        raise ConfigError(msg)
    return Config(contact=contact, home=_home(raw.get("home"), path))


def _home(raw: object, path: pathlib.Path) -> Place | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not {"name", "lat", "lon"} <= raw.keys():
        msg = f"{path}: [home] needs a name, lat and lon."
        raise ConfigError(msg)
    return Place(name=str(raw["name"]), lat=rounded(float(raw["lat"])), lon=rounded(float(raw["lon"])))

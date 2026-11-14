"""The local config: who we are to MET, and where home is.

Every place here is made up, near 61.00 N 9.00 E. The real home lives only in
the owner's own config file, never in this repository.
"""

import pathlib

import pytest

from weather_mcp.config import ConfigError, config_path, load_config


def write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_the_contact_has_no_default(tmp_path):
    path = write(tmp_path, '[home]\nname = "Testheim"\nlat = 61.0\nlon = 9.0\n')
    with pytest.raises(ConfigError, match="contact"):
        load_config(path)


def test_an_empty_contact_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="contact"):
        load_config(write(tmp_path, 'contact = "  "\n'))


def test_a_missing_file_says_where_to_write_it(tmp_path):
    with pytest.raises(ConfigError, match=r"config\.toml"):
        load_config(tmp_path / "config.toml")


def test_home_is_rounded_to_two_decimals(tmp_path):
    home_table = '[home]\nname = "Testheim"\nlat = 61.0049\nlon = 8.9951\n'
    path = write(tmp_path, 'contact = "https://example.org/weather-mcp"\n' + home_table)
    home = load_config(path).home
    assert home is not None
    assert (home.lat, home.lon) == (61.0, 9.0)
    assert home.name == "Testheim"


def test_home_is_optional(tmp_path):
    config = load_config(write(tmp_path, 'contact = "https://example.org/weather-mcp"\n'))
    assert config.home is None
    assert config.contact == "https://example.org/weather-mcp"


def test_a_home_without_coordinates_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="home"):
        load_config(write(tmp_path, 'contact = "x"\n[home]\nname = "Testheim"\n'))


def test_the_config_lives_under_the_users_config_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "weather-mcp" / "config.toml"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config_path() == pathlib.Path.home() / ".config" / "weather-mcp" / "config.toml"

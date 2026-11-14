"""The command that starts the server."""

import importlib.metadata

from weather_mcp.cli import main, user_agent
from weather_mcp.config import Config


def test_serving_without_a_config_says_where_to_write_it(tmp_path, capsys):
    assert main(["serve", "--config", str(tmp_path / "config.toml")]) == 2
    assert "config.toml" in capsys.readouterr().err


def test_serving_without_a_contact_is_refused(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text("")
    assert main(["serve", "--config", str(path)]) == 2
    assert "contact" in capsys.readouterr().err


def test_the_user_agent_names_the_program_and_the_contact():
    version = importlib.metadata.version("weather-mcp")
    agent = user_agent(Config(contact="https://example.org/weather-mcp", home=None))
    assert agent == f"weather-mcp/{version} https://example.org/weather-mcp"

"""The MCP server: the weather tools, over stdio for a voice session."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from weather_mcp.weather import Weather

INSTRUCTIONS = (
    "The weather in Norway, from MET Norway. Read each 'say' aloud as it is. No place means the owner's home."
)
#: Changes nothing anywhere; it only reads the forecast.
LOOKS = ToolAnnotations(read_only_hint=True)
#: What the voice hears when weather-mcp itself fails, so it never hears only that the tool failed.
BROKE = "That went wrong inside weather-mcp. Try again, and if it fails again, check its log."


def build_server(weather: Weather) -> MCPServer[Any]:
    """The MCP server with weather_now."""
    server: MCPServer[Any] = MCPServer(name="weather", instructions=INSTRUCTIONS)

    @server.tool(
        annotations=LOOKS,
        description="The weather right now. 'place' is a place in Norway as the owner said it,"
        " such as 'Bergen' or 'Moen i Agder'; omit it for home. Data from MET Norway and Kartverket.",
    )
    async def weather_now(place: str | None = None) -> dict[str, Any]:
        try:
            return await weather.now(place)
        except Exception as failure:  # noqa: BLE001 - whatever broke, the voice gets a sentence
            # RULE: a failure logs no coordinates
            # Only the kind of failure: its message or traceback can carry the
            # request's URL, and for home that URL is the home point.
            logging.getLogger(__name__).error("weather_now failed: %s", type(failure).__name__)  # noqa: TRY400
            return {"success": False, "say": BROKE}

    return server

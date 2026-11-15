"""The MCP server: the weather tools, over stdio for a voice session."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

if TYPE_CHECKING:
    from weather_mcp.weather import Weather

INSTRUCTIONS = (
    "The weather in Norway, from MET Norway. Read each 'say' aloud as it is. Send the phone's"
    " position as lat, lon and accuracy_m when you have it, so 'the weather here' is where the"
    " owner is. A place they name comes first; with neither, it is the owner's home."
)
#: Changes nothing anywhere; it only reads the forecast.
LOOKS = ToolAnnotations(read_only_hint=True)
#: What the voice hears when weather-mcp itself fails, so it never hears only that the tool failed.
BROKE = "That went wrong inside weather-mcp. Try again, and if it fails again, check its log."
#: The voice gives up on a call after about 15 seconds; every answer comes before then.
ANSWER_WITHIN = 12.0
#: What the voice hears when the services are too slow to answer in time.
SLOW = "MET is slow to answer just now. Ask again in a moment."


def build_server(weather: Weather, *, answer_within: float = ANSWER_WITHIN) -> MCPServer[Any]:
    """The MCP server with weather_now."""
    server: MCPServer[Any] = MCPServer(name="weather", instructions=INSTRUCTIONS)

    @server.tool(
        annotations=LOOKS,
        description="The weather right now. 'place' is a place in Norway as the owner said it,"
        " such as 'Bergen' or 'Moen i Agder'. Send the phone's position as lat, lon and accuracy_m"
        " when you have it; a named place comes first, and with neither it is home."
        " Data from MET Norway and Kartverket.",
    )
    async def weather_now(
        place: str | None = None,
        lat: Annotated[float | None, Field(description="The phone's latitude, if known.")] = None,
        lon: Annotated[float | None, Field(description="The phone's longitude, if known.")] = None,
        accuracy_m: Annotated[
            float | None, Field(description="How exact the phone's position is, in metres.")
        ] = None,
    ) -> dict[str, Any]:
        try:
            asked = weather.now(place, lat=lat, lon=lon, accuracy_m=accuracy_m)
            # RULE: every answer comes within the deadline
            return await asyncio.wait_for(asked, answer_within)
        except TimeoutError:
            return {"success": False, "say": SLOW}
        except Exception as failure:  # noqa: BLE001 - whatever broke, the voice gets a sentence
            # RULE: a failure logs no coordinates
            # Only the kind of failure: its message or traceback can carry the
            # request's URL, and for home that URL is the home point.
            logging.getLogger(__name__).error("weather_now failed: %s", type(failure).__name__)  # noqa: TRY400
            return {"success": False, "say": BROKE}

    return server

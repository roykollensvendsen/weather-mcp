"""The MCP server: the weather tools, over stdio for a voice session."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from weather_mcp.weather import Weather

INSTRUCTIONS = (
    "The weather in Norway, from MET Norway. Read each 'say' aloud as it is. Send the phone's"
    " position as lat, lon and accuracy_m when you have it, so 'the weather here' is where the"
    " owner is. A place they name comes first; with neither, it is the owner's home."
)
#: Changes nothing anywhere; it only reads the forecast.
LOOKS = ToolAnnotations(read_only_hint=True)
#: How a day may be given. The plugin works the date out itself, from today in Oslo.
DAY = (
    "The day asked about, as the owner said it, in Norwegian or English: 'today', 'i morgen',"
    " a weekday such as 'fredag' or 'on Friday', 'neste fredag', or a date such as '20.11' or"
    " '20. november'."
    " Tomorrow if not said."
)
#: How the last day of the coming days may be given.
UNTIL = (
    "The last day to cover, as the owner said it: 'søndag' or 'Sunday' for the rest of the week,"
    " or a weekday or date such as '23.11'. Five days from tomorrow if not said."
)
#: What the voice hears when weather-mcp itself fails, so it never hears only that the tool failed.
BROKE = "That went wrong inside weather-mcp. Try again, and if it fails again, check its log."
#: The voice gives up on a call after about 15 seconds; every answer comes before then.
ANSWER_WITHIN = 12.0
#: What the voice hears when the services are too slow to answer in time.
SLOW = "MET is slow to answer just now. Ask again in a moment."


#: The phone's position, as the voice sends it; both tools take it.
Lat = Annotated[float | None, Field(description="The phone's latitude, if known.")]
Lon = Annotated[float | None, Field(description="The phone's longitude, if known.")]
Accuracy = Annotated[float | None, Field(description="How exact the phone's position is, in metres.")]

#: A query string in a logged address: for MET it holds the point, home's or the phone's.
QUERY = re.compile(r"\?[^\s\"']*")


#: The loggers httpx and httpcore write request addresses on.
LOGGERS = (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
)


class NoQueryStrings(logging.Filter):
    """Cut the query string out of every address a log line holds, and keep the line."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the line without its query strings; never drop it."""
        # RULE: a position is never logged
        record.msg, record.args = QUERY.sub("?…", record.getMessage()), None
        return True


NO_QUERY_STRINGS = NoQueryStrings()


def hide_query_strings() -> None:
    """Put the filter on the loggers that write request addresses, once.

    A logger's filter misses what its children log, so httpcore's children are named.
    """
    for name in LOGGERS:
        # Removing first keeps one filter however many servers are built.
        logging.getLogger(name).removeFilter(NO_QUERY_STRINGS)
        logging.getLogger(name).addFilter(NO_QUERY_STRINGS)


#: What a simulated server tells the voice first, and what each of its answers starts with.
SIMULATED = "SIMULATED: this is made-up weather, not MET's. Say so when you report it. "
SAID_SIMULATED = "Simulated: "


def build_server(
    weather: Weather, *, answer_within: float = ANSWER_WITHIN, simulated: bool = False
) -> MCPServer[Any]:
    """The MCP server with the three weather tools; made-up, and saying so, if simulated."""
    hide_query_strings()
    server: MCPServer[Any] = MCPServer(
        name="weather-simulated" if simulated else "weather",
        instructions=SIMULATED + INSTRUCTIONS if simulated else INSTRUCTIONS,
    )

    async def _answer(tool: str, asked: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
        answer = await _within(tool, asked)
        # RULE: every simulated answer says simulated first
        return {**answer, "say": SAID_SIMULATED + answer["say"]} if simulated else answer

    async def _within(tool: str, asked: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
        """The tool's answer, or a sentence when it is too slow or anything inside breaks."""
        try:
            # RULE: every answer comes within the deadline
            return await asyncio.wait_for(asked, answer_within)
        except TimeoutError:
            return {"success": False, "say": SLOW}
        except Exception as failure:  # noqa: BLE001 - whatever broke, the voice gets a sentence
            # RULE: a failure logs no coordinates
            # Only the kind of failure: its message or traceback can carry the
            # request's URL, and for home that URL is the home point.
            logging.getLogger(__name__).error("%s failed: %s", tool, type(failure).__name__)  # noqa: TRY400
            return {"success": False, "say": BROKE}

    @server.tool(
        annotations=LOOKS,
        description="The weather right now. 'place' is a place in Norway as the owner said it,"
        " such as 'Bergen' or 'Moen i Agder'. Send the phone's position as lat, lon and accuracy_m"
        " when you have it; a named place comes first, and with neither it is home."
        " Data from MET Norway and Kartverket.",
    )
    async def weather_now(
        place: str | None = None,
        lat: Lat = None,
        lon: Lon = None,
        accuracy_m: Accuracy = None,
    ) -> dict[str, Any]:
        return await _answer("weather_now", weather.now(place, lat=lat, lon=lon, accuracy_m=accuracy_m))

    @server.tool(
        annotations=LOOKS,
        description="The forecast for one day, up to about nine days ahead, in one sentence: the"
        " temperature range, rain, wind, and the sky in the morning, at midday and in the evening."
        " Use it when one day is asked about; for the coming days together use weather_week."
        " Send the phone's position as lat, lon and accuracy_m when you have it; a named place"
        " comes first, and with neither it is home. Data from MET Norway and Kartverket.",
    )
    async def weather_forecast(
        day: Annotated[str, Field(description=DAY)] = "tomorrow",
        place: str | None = None,
        lat: Lat = None,
        lon: Lon = None,
        accuracy_m: Accuracy = None,
    ) -> dict[str, Any]:
        return await _answer(
            "weather_forecast", weather.forecast(place, day=day, lat=lat, lon=lon, accuracy_m=accuracy_m)
        )

    @server.tool(
        annotations=LOOKS,
        description="The coming days in a few short sentences: one line a day with the temperature"
        " range, rain, snow or dry, and the wind when it is strong, with alike days said together;"
        " then the wettest and the driest day. Five days from tomorrow, or up to 'until'. Use it for"
        " 'the coming days', 'this week' or 'the rest of the week'; for one day use weather_forecast."
        " Send the phone's position as lat, lon and accuracy_m when you have it; a named place"
        " comes first, and with neither it is home. Data from MET Norway and Kartverket.",
    )
    async def weather_week(
        place: str | None = None,
        until: Annotated[str | None, Field(description=UNTIL)] = None,
        lat: Lat = None,
        lon: Lon = None,
        accuracy_m: Accuracy = None,
    ) -> dict[str, Any]:
        return await _answer(
            "weather_week", weather.week(place, until=until, lat=lat, lon=lon, accuracy_m=accuracy_m)
        )

    return server

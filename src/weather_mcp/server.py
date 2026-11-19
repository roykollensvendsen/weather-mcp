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
#: How the hour asked about may be given.
FROM = (
    "The hour asked about, or the start of the span, as the owner said it: '15', '15:00', '15.00',"
    " 'kl. 15', 'klokka 15' or '3 pm'. A bare hour is on a 24-hour clock."
)
#: How the end of a span may be given.
TO = (
    "The end of the span, said as from_time is: 'from 14 to 18' is from_time '14' and to_time"
    " '18'. Leave it out for one hour."
)
#: How the day of a time may be given.
WHEN = "The day, said as for weather_forecast: 'today', 'i morgen', 'fredag' or '20.11'. Today if not said."
#: Which detail weather_detail is asked for.
WHAT = (
    "The one detail asked about: 'uv', 'humidity', 'dew point', 'fog' (also for visibility) or"
    " 'wind' (with its gusts and direction)."
)
#: The hour a detail is asked for; with none it is now, or the whole of another day.
DETAIL_FROM = FROM + " Leave it out for now, or for the whole of another day."
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
    """The MCP server with the five weather tools; made-up, and saying so, if simulated."""
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
        description="The weather right now, and from MET's radar whether rain is coming in the next"
        " two hours. 'place' is a place in Norway as the owner said it,"
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
        " Use it when one day is asked about; for a time of day use weather_hours, and for the"
        " coming days together use weather_week."
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

    @server.tool(
        annotations=LOOKS,
        description="The weather at one clock time, or between two, in one sentence: the"
        " temperature, the sky, rain and wind. Use it only when a time of day is named, such as"
        " 'at 15' or 'from 14 to 18 tomorrow'; for a whole day use weather_forecast, and for the"
        " coming days weather_week. Send the phone's position as lat, lon and accuracy_m when you"
        " have it; a named place comes first, and with neither it is home."
        " Data from MET Norway and Kartverket.",
    )
    async def weather_hours(  # noqa: PLR0913, PLR0917 - each input as the voice sends it
        from_time: Annotated[str, Field(description=FROM)],
        to_time: Annotated[str | None, Field(description=TO)] = None,
        place: str | None = None,
        day: Annotated[str, Field(description=WHEN)] = "today",
        lat: Lat = None,
        lon: Lon = None,
        accuracy_m: Accuracy = None,
    ) -> dict[str, Any]:
        asked = weather.hours(
            place, from_time=from_time, to_time=to_time, day=day, lat=lat, lon=lon, accuracy_m=accuracy_m
        )
        return await _answer("weather_hours", asked)

    @server.tool(
        annotations=LOOKS,
        description="One detail beyond the basics, as Yr's app shows it, said as its value and the"
        " time it is for: the UV index on a clear sky, humidity, dew point, fog, or the wind with"
        " its gusts and direction. Use it only when one of these is asked about; for the weather"
        " itself use the other tools. With a span of time it gives a range, the peak or the"
        " strongest hour. Send the phone's position as lat, lon and accuracy_m when you have it;"
        " a named place comes first, and with neither it is home. Data from MET Norway and Kartverket.",
    )
    async def weather_detail(  # noqa: PLR0913, PLR0917 - each input as the voice sends it
        what: Annotated[str, Field(description=WHAT)],
        day: Annotated[str, Field(description=WHEN)] = "today",
        from_time: Annotated[str | None, Field(description=DETAIL_FROM)] = None,
        to_time: Annotated[str | None, Field(description=TO)] = None,
        place: str | None = None,
        lat: Lat = None,
        lon: Lon = None,
        accuracy_m: Accuracy = None,
    ) -> dict[str, Any]:
        asked = weather.detail(
            what,
            place,
            day=day,
            from_time=from_time,
            to_time=to_time,
            lat=lat,
            lon=lon,
            accuracy_m=accuracy_m,
        )
        return await _answer("weather_detail", asked)

    return server

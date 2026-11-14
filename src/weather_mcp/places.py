"""Turn a spoken Norwegian place name into a point, through Kartverket.

Kartverket's place-name service needs no key and is CC BY 4.0. Towns and
built-up areas win over farms and hills of the same name. A name shared by
several such places comes back as a question, never as a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from weather_mcp.config import Place, rounded

if TYPE_CHECKING:
    import httpx

KARTVERKET = "https://api.kartverket.no/stedsnavn/v1/navn"
#: The kinds a person means when they ask for the weather "in" a place.
SETTLED = {"By", "Tettsted", "Tettbebyggelse", "Kommune", "Bydel"}
#: At most this many counties are read out when a name is shared.
MOST_CHOICES = 3


@dataclass(frozen=True)
class Found:
    """One place, or the counties to choose between, or neither."""

    place: Place | None
    choices: list[str] = field(default_factory=list)


def _county(hit: dict[str, Any]) -> str:
    counties = hit.get("fylker") or [{}]
    return str(counties[0].get("fylkesnavn", ""))


def _place(hit: dict[str, Any]) -> Place:
    point = hit["representasjonspunkt"]
    return Place(
        name=str(hit["skrivemåte"]), lat=rounded(float(point["nord"])), lon=rounded(float(point["øst"]))
    )


class PlaceFinder:
    """Looks names up once, and keeps what it found."""

    def __init__(self, http: httpx.AsyncClient, user_agent: str) -> None:
        """Wrap an open client; every request carries the given User-Agent."""
        self._http, self._agent = http, user_agent
        self._kept: dict[str, list[dict[str, Any]]] = {}

    async def find(self, spoken: str) -> Found:
        """The place a spoken name means; "Moen i Agder" names the county too."""
        name, _, county = spoken.strip().partition(" i ")
        hits = [
            h for h in await self._hits(name) if str(h.get("skrivemåte", "")).casefold() == name.casefold()
        ]
        if county:
            hits = [h for h in hits if _county(h).casefold() == county.strip().casefold()]
        settled = [h for h in hits if h.get("navneobjekttype") in SETTLED] or hits
        by_county: dict[str, dict[str, Any]] = {}
        for hit in settled:
            by_county.setdefault(_county(hit), hit)
        # RULE: a shared name asks which one
        if len(by_county) > 1:
            return Found(place=None, choices=sorted(by_county)[:MOST_CHOICES])
        if not by_county:
            return Found(place=None)
        return Found(place=_place(next(iter(by_county.values()))))

    async def _hits(self, name: str) -> list[dict[str, Any]]:
        key = name.casefold()
        if key not in self._kept:
            params = {"sok": name, "fuzzy": "false", "utkoordsys": "4258", "treffPerSide": "20"}
            response = await self._http.get(KARTVERKET, params=params, headers={"User-Agent": self._agent})
            response.raise_for_status()
            self._kept[key] = list(response.json().get("navn", []))
        return self._kept[key]

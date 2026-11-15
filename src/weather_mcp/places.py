"""Turn a spoken Norwegian place name into a point, through Kartverket.

Kartverket's place-name service needs no key and is CC BY 4.0. Only places
people live in are asked for, so farms and hills of the same name never crowd
out a town. A name shared by several of them comes back as a question, never
as a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from weather_mcp.config import Place, rounded

if TYPE_CHECKING:
    import httpx

KARTVERKET = "https://api.kartverket.no/stedsnavn/v1/sted"
#: The kinds a person means when they ask for the weather "in" a place, as the
#: codes Kartverket's filter takes. A real "Moen" has over a thousand hits, and
#: without this filter the towns are not on the first page.
SETTLED = (
    "by",
    "tettsted",
    "tettbebyggelse",
    "tettsteddel",
    "bygdelagBygd",
    "kommune",
    "bydel",
    "administrativBydel",
)
#: Settled places sharing one name are far fewer than this.
PAGE = 100
#: At most this many counties are read out when a name is shared.
MOST_CHOICES = 3


@dataclass(frozen=True)
class Found:
    """One place, or the counties to choose between, or neither."""

    place: Place | None
    choices: list[str] = field(default_factory=list)


def _names(hit: dict[str, Any]) -> list[str]:
    return [str(n.get("skrivemåte", "")) for n in hit.get("stedsnavn", [])]


def _county_names(hit: dict[str, Any]) -> list[str]:
    """A county's name in each of its languages, as in "Troms - Romsa - Tromssa"."""
    counties = hit.get("fylker") or [{}]
    return [part.strip() for part in str(counties[0].get("fylkesnavn", "")).split(" - ")]


def _place(hit: dict[str, Any]) -> Place:
    point = hit["representasjonspunkt"]
    return Place(name=_names(hit)[0], lat=rounded(float(point["nord"])), lon=rounded(float(point["øst"])))


def _municipality(hit: dict[str, Any]) -> str:
    municipalities = hit.get("kommuner") or [{}]
    return str(municipalities[0].get("kommunenavn", ""))


def _one_of(hits: list[dict[str, Any]]) -> Found:
    """One place, or the question that tells them apart.

    A town and the municipality of the same name are one place, so hits are
    counted per municipality. Counties are asked about when they tell the
    places apart, and municipalities when two places share a county.
    """
    by_municipality: dict[tuple[str, str], dict[str, Any]] = {}
    for hit in hits:
        by_municipality.setdefault((_county_names(hit)[0], _municipality(hit)), hit)
    counties = {county for county, _ in by_municipality}
    # RULE: a shared name asks which one
    if len(by_municipality) > 1:
        # Counties first when they tell the places apart, or when there are too
        # many places to read out; "Moen i <county>" then narrows to municipalities.
        by_county = len(counties) == len(by_municipality) or len(by_municipality) > MOST_CHOICES
        names = counties if by_county else {municipality for _, municipality in by_municipality}
        return Found(place=None, choices=sorted(names)[:MOST_CHOICES])
    if not by_municipality:
        return Found(place=None)
    return Found(place=_place(next(iter(by_municipality.values()))))


def _lies_in(hit: dict[str, Any], area: str) -> bool:
    """Whether a spoken county or municipality is where this place is."""
    return area.casefold() in (n.casefold() for n in [*_county_names(hit), _municipality(hit)])


class PlaceFinder:
    """Looks names up once, and keeps what it found."""

    def __init__(self, http: httpx.AsyncClient, user_agent: str) -> None:
        """Wrap an open client; every request carries the given User-Agent."""
        self._http, self._agent = http, user_agent
        self._kept: dict[str, list[dict[str, Any]]] = {}

    async def find(self, spoken: str) -> Found:
        """The place a spoken name means.

        "Mo i Rana" is first looked up whole, since many names say "i". Only
        when that finds nothing is "Moen i Agder" read as a name and a county,
        or a name and a municipality.
        """
        spoken = spoken.strip()
        whole = await self._named(spoken)
        name, i, area = spoken.rpartition(" i ")
        if whole or not i:
            return _one_of(whole)
        return _one_of([h for h in await self._named(name) if _lies_in(h, area.strip())])

    async def _named(self, name: str) -> list[dict[str, Any]]:
        """Settled places with exactly this name, in any of their spellings."""
        return [h for h in await self._hits(name) if name.casefold() in (n.casefold() for n in _names(h))]

    async def _hits(self, name: str) -> list[dict[str, Any]]:
        key = name.casefold()
        if key not in self._kept:
            params: dict[str, str | list[str]] = {
                "sok": name,
                "fuzzy": "false",
                "utkoordsys": "4258",
                "treffPerSide": str(PAGE),
                "navneobjekttype": list(SETTLED),
            }
            response = await self._http.get(KARTVERKET, params=params, headers={"User-Agent": self._agent})
            response.raise_for_status()
            self._kept[key] = list(response.json().get("navn", []))
        return self._kept[key]

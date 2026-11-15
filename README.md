# weather-mcp

The weather in Norway by voice, from MET Norway's open data, as an MCP server and an optional claude-voice plugin.

It gives a voice session one tool so far, `weather_now(place?, lat?, lon?, accuracy_m?)`.
A place is a name in Norway, as spoken: "Bergen", or "Moen i Agder" when a name is
shared. The voice sends the phone's position, so "the weather here" is where you are.
A named place comes first, then the position, then home. The answer is one short
sentence to read aloud.

Data from MET Norway (NLOD 2.0 and CC BY 4.0), and place names from Kartverket (CC BY 4.0).

MET's [terms of service](https://docs.api.met.no/doc/TermsOfService) ask a person to read
and accept them before use. The owner of this repository accepted them on 2026-11-14.
Anyone running their own copy must read and accept them too.

## Set up

MET refuses requests that do not say who is asking. So the config must name a contact,
and there is no default. The server refuses to start without one. Use your own fork's
URL or your own website, not this one. Write `~/.config/weather-mcp/config.toml`:

```toml
contact = "https://github.com/roykollensvendsen/weather-mcp"

[home]              # optional; rounded to 2 decimals, about 1 km
name = "<the name you say>"
lat = 0.00
lon = 0.00
```

Home stays in that file. It is never in this repository, its tests or its logs. The
phone's position is never logged or written anywhere. It is rounded like home before
MET is asked, and kept in memory only.

Forecasts are kept in `~/.cache/weather-mcp/forecasts.json`, so a restart never asks MET
again too early. Only you can read it. It holds each point asked about, rounded, home
included, but never the phone's position. A place whose forecast expired over a day ago is dropped, except home. Delete
the file at any time; it is rebuilt.

Then start the server for a voice session:

```console
$ weather-mcp serve --help
usage: weather-mcp serve [-h] [--config FILE]

options:
  -h, --help     show this help message and exit
  --config FILE  the config file, if not the usual one
```

## The gates

Every one of these runs in continuous integration, and all of them run here:

```console
$ uv run ruff check .
All checks passed!
```

<!-- not run: the workflow runs each of these; nesting them here would run the suite inside itself -->
```bash
uv run ruff format --check .   # layout
uv run mypy src                # types
python scripts/private_data_scan.py --tracked --history   # nothing private, ever
uv run pytest -q               # behaviour
python scripts/mutate.py       # that each rule's own test can fail
```

`CONTRIBUTING.md` says what each one is for, and
[`decisions/`](decisions/README.md) records the choices that shaped them,
including how a change is made here.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

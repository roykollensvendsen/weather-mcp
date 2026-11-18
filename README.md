# weather-mcp

The weather in Norway by voice, from MET Norway's open data, as an MCP server and an optional claude-voice plugin.

It gives a voice session four tools. `weather_now(place?, lat?, lon?, accuracy_m?)` says
the weather right now, and from MET's radar whether rain is coming in the next two
hours. `weather_forecast(day?, place?, lat?, lon?, accuracy_m?)` says one
day, up to about nine days ahead: the temperature range, rain, wind, and the sky in the
morning, at midday and in the evening. `weather_week(until?, place?, lat?, lon?, accuracy_m?)`
says the coming days, five from tomorrow or up to `until`, one short line a day, then the
wettest and the driest. `weather_hours(from_time, to_time?, place?, day?, lat?, lon?,
accuracy_m?)` says one clock hour, or the hours between two: "at 15", "from 14 to 18" or
"tomorrow between 8 and 12".

A day is said as the owner says it, in Norwegian or English: "i morgen", "fredag", "on
Friday", "neste fredag", "20.11" or "20. november". A time is "15", "15:00", "15.00",
"kl. 15" or "3 pm"; a bare hour is on a 24-hour clock, and the answer says it back. The plugin works the date out itself, from today in
Oslo. Beyond the first two and a half days MET gives six-hour blocks, so a range there
starts with "about". All four read the same forecast from MET, so asking them all asks once.
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
usage: weather-mcp serve [-h] [--config FILE] [--simulate]

options:
  -h, --help     show this help message and exit
  --config FILE  the config file, if not the usual one
  --simulate     use made-up weather and places; touches no network
```

To try the tools by voice without MET, Kartverket or a config, serve with `--simulate`.
The weather and the one place, Testheim, are made up, and every answer starts
"Simulated:".

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

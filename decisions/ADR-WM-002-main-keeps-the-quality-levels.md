# ADR-WM-002: Main keeps the quality levels, so a pull request never records them

## Status

Accepted 2026-11-15. It follows rule 16 of the voice plugins' shared standard
(claude-voice docs/plugin-standard.md), which the owner accepted on 2026-11-10.
It takes over tv-mcp's
[ADR-TM-002](https://github.com/roykollensvendsen/tv-mcp/blob/main/decisions/ADR-TM-002-main-keeps-the-quality-levels.md)
and claude-voice's
[ADR-CV-009](https://github.com/roykollensvendsen/claude-voice/blob/main/decisions/ADR-CV-009-main-keeps-the-quality-levels.md)
unchanged in substance.

## Context

The gates here pass or fail. A suite that loses tests, coverage that drifts
down, or a function that grows more tangled all stay green. The code-health
page of the voice plugins shows each plugin's levels, and it reads them from a
`quality-levels` artifact that main keeps with its own runs.

The two records above already settled how. Keeping the levels in a file that
each pull request updates made the file a queue: one merge made every other
open pull request stale. Measuring here is cheap: the suite takes seconds, and
the mutation check about a minute.

## Options considered

- **Do nothing.** Slow decay goes unseen, and the code-health page has nothing
  to show. Not taken.
- **Keep the levels in a file each pull request updates.** Every merge breaks
  every other open pull request. Not taken.
- **Measure main and the pull request in every check.** Nothing stored, but
  every check takes twice as long. Kept only as the fallback below.
- **Main keeps its measured levels with each of its runs, and a pull request
  compares with them.** **Chosen**, as in the two records above.

## Decision

After every push to main, continuous integration measures the levels and keeps
them with that run as `quality-levels`. A pull request's check compares with
the levels main kept for the commit it is merged onto. It fails when a level
is worse, unless a `Ratchet-Exception:` line in the pull request names it.
When main's levels are missing, the check measures that commit in a copy.
`quality.json` keeps only the suite's time budget, a limit set by hand.

The layers are two: the core, which knows nothing of MCP, and the top, the
server and the command line. `layer()` in `scripts/ratchet.py` is the map.

## Consequences

- Merging one pull request never breaks another. Measured numbers never go in
  the repository.
- **Worse:** the levels do not show in a pull request's diff, only in the
  check's output and in main's runs.
- **Worse:** GitHub keeps main's run results for 90 days by default. Past that,
  the check measures the base itself, which doubles its time.
- **Worse:** a new module must be given a layer in `scripts/ratchet.py`, or the
  check fails it as a breach.

## Related

tv-mcp's ADR-TM-002, claude-voice's ADR-CV-009, `scripts/ratchet.py`,
`quality.json`, the `quality` job in `.github/workflows/checks.yml`, and "The
quality ratchet" in [`CONTRIBUTING.md`](../CONTRIBUTING.md#the-quality-ratchet).

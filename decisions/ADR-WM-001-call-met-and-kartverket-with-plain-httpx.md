# ADR-WM-001: Call MET Norway and Kartverket with plain httpx

## Status

Accepted, 2026-11-14, by the claude-voice manager for the owner. An objection returns it to Proposed.

## Context

The server asks two open services for data. MET Norway's api.met.no gives the forecast. Kartverket's
place-name service turns a spoken name into a point. Neither needs a key or a login.

MET's terms make the client responsible for three things
([TermsOfService](https://docs.api.met.no/doc/TermsOfService), read 2026-11-14):

- an identifying User-Agent on every request;
- coordinates cut to at most four decimals;
- caching by `Expires`, asking again with `If-Modified-Since`, and slowing down on a 429.

The plugin is the "local proxy" those terms ask for. So the cache rules are this project's own
behaviour to test, whichever library sends the request.

## Options considered

- **PyMetno 0.14.0** (MIT, the client behind Home Assistant's met integration). Not taken. It
  parses the forecast for us, but its cache and its handling of a 429 are its own. Our tests
  would then check a library's choices rather than the rules MET states. It also covers only
  MET, so Kartverket would need httpx anyway.
- **metno-locationforecast 2.1.0.** Not taken: no release since 2024-12.
- **The standard library's urllib.** Not taken. It has no async client and no mock transport.
  A fake built on it would need a local server.
- **Do nothing and use Yr's app.** Not taken: it has no voice, and claude-voice already takes
  plugins.

## Decision

Send every request through one `httpx.AsyncClient`, wrapped by a small cache of our own. The cache
keeps `Expires` and `Last-Modified` per URL, and answers from what it holds on a 429. The tests swap
the network for `httpx.MockTransport`, with a fake that copies MET's and Kartverket's real limits.

## Consequences

- The forecast format is parsed here. A change MET makes to it breaks this code, and no library
  absorbs it for us. MET flags a deprecated product with status 203, which is logged.
- The cache rules are tested directly, against a fake that refuses what MET refuses.
- One dependency instead of two, and the same one tv-mcp already uses.
- Worse: a fake can only copy the limits we know about. A rule MET adds later stays unseen until
  a real request meets it.

## Related

- [`deferred.md`](deferred.md)
- The design note for this plugin, kept outside the repository.

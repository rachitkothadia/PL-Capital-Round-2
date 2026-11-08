# Optional local relationship graph

The core application uses SQLite on every platform. On supported macOS/Linux,
`uv run --extra graph pl-capital` enables the optional FalkorDBLite package.
macOS requires the separately installed OpenMP runtime (`libomp`). Native Windows
uses the complete SQLite-only path. No Docker or external graph service is needed.

`GRAPH_BACKEND=auto|lite|off` controls selection. `lite` reports an actionable
diagnostic if initialization fails; `auto` falls back visibly; `off` never imports
native dependencies. Graph availability never grants access to write SQLite.

Trusted ingestion creates Table-HAS_COLUMN-Column, Table-REFERENCES-Table,
Portfolio-HOLDS-Security and Security-IN_SECTOR-Sector relationships. A namespace
contains the dataset checksum and graph schema version. Parameterized `MERGE`
operations and a completion marker make interrupted/repeated ingestion idempotent.
An interprocess file lock serializes ingestion. Retrieval uses fixed, bounded,
parameterized `GRAPH.RO_QUERY` traversals; users cannot submit Cypher.

Graph values provide relationship context only. Quantitative answers always come
from SQLite. Context and status explicitly identify actual native use or fallback.

Before native retrieval, a bounded SQLite schema/entity catalogue identifies
recognized names and analytical terms. Stopwords and unknown noise words are not
used as graph search terms. Synonyms such as funds/portfolios and stocks/equities
select known schema families. A spelling correction requires exactly one known
schema/entity token within one character edit or adjacent transposition; short or
ambiguous tokens are left unresolved. This never changes the user's financial
question or invents portfolio identifiers.

Simple single-table lookups, including portfolio counts, use SQLite schema
without starting or querying the native graph. Unrelated prose also skips it.
Known company names alone do not justify graph use for nonanalytical questions.
`GraphContext(settings, lazy=True)` defers native startup until relationship
context is useful; the explicit graph-status command retains eager diagnostics.

For relevant requests, fixed traversals retrieve matching entity IDs and their
security/sector relationships, selected columns and foreign-key joins. Actual
Cypher and bound parameters are recorded. Native `used=true` requires matching
entities or contributed join evidence, rather than merely a running backend or
schema-shaped response. Generic historical/window queries can benefit from real
schema joins even without a named portfolio or sector. The result also records
`attempted`, `retrieval_ms`, recognized `terms`, disclosed `normalizations`, and
`useful_evidence`. A no-evidence result falls back explicitly to SQLite metadata.

Native retrieval uses `ro_query` exclusively. Each call has at most a 250 ms query
timeout; a one-second cooperative budget is checked between read calls after
startup. Startup lock waits and socket timeouts are separately capped at two
seconds. Startup latency is recorded separately in backend status; the response's
retrieval time includes startup when it occurs. Startup/cleanup involve native
process operations, so this is not a hard one-second wall-clock guarantee.
Context targets less than 18,000 JSON characters
and contains no graph-based financial calculations. The planner separately
receives authoritative SQLite schema.

An actual macOS arm64 profile measured lazy construction at 0.007 ms and the
misspelled count question at 8.791 ms with no native startup/queries. A first
Technology-sector traversal took 376.396 ms including startup; a warm corrected
sector spelling took 6.436 ms, and risk/performance join-only context took 3.494 ms.
These are local samples, not performance guarantees. The previous eager path
spent 401.831 ms starting the server before a simple count and incorrectly claimed
graph use for the noise terms `maby`, `do`, and `we`.

If a graph query fails mid-session, the adapter closes the native connection and
returns SQLite-introspected schema, foreign keys, and matching entity hints. Its
`used` field becomes false, backend becomes `sqlite`, and the fallback reason names
the error category. A native outage cannot substitute fabricated graph evidence.

The FalkorDBLite Python wrapper is BSD-3-Clause; the bundled FalkorDB engine has
its own SSPL v1 license. Dependencies are installed separately, not bundled into
this application's wheel. Review upstream terms for redistribution or hosting.

References: [FalkorDBLite](https://github.com/FalkorDB/falkordblite),
[driver](https://github.com/FalkorDB/falkordb-py),
[wrapper license](https://github.com/FalkorDB/falkordblite/blob/master/LICENSE.txt),
[engine license](https://github.com/FalkorDB/FalkorDB/blob/master/LICENSE.txt).

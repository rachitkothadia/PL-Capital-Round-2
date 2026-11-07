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

For each question, bounded token matching discovers portfolio and sector nodes.
Fixed traversals retrieve their security/sector relationships, selected schema
columns, and foreign-key join paths. Actual query text and parameter values appear
in the returned context. Native retrieval uses `ro_query` exclusively. Context is
capped below 20,000 JSON characters and does not contain graph-based financial
calculations. The SQL planner separately receives authoritative SQLite schema.

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

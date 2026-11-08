# Local graph context

SQLite remains the financial source of truth. FalkorDBLite supplies entity IDs,
holdings relationships and schema join paths to the Gemini planner; it never
provides a replacement price or computed financial answer. No Docker, credentials
or hosted graph service are required. The package manages a local Redis/FalkorDB
subprocess through a private Unix socket; “embedded” does not mean in-process.

## Installation and verified environment

Python 3.12–3.14 is required by this project. `falkordblite>=0.11,<1` is a default
dependency on macOS/Linux, so normal `uv sync --locked` and bare `uv run pl-capital`
retain the graph package. The former `graph` extra remains a compatible alias.

```sh
uv sync --locked
uv run python -c 'from redislite.falkordb_client import FalkorDB; print("import ok")'
uv run pl-capital doctor --graph
uv run pl-capital graph status
uv run pl-capital graph build
uv run pl-capital graph rebuild
uv run pl-capital
```

The distribution is named `falkordblite`, while its import module is
`redislite.falkordb_client`. The original bare `uv run` failed with
`ModuleNotFoundError: No module named 'redislite'`: graph was optional and omitted
by default synchronization. The repaired locked environment installed
FalkorDBLite 0.11.0 and FalkorDB driver 1.8.1 under the same Python 3.13.11 used by
the application. Real native Cypher was verified on macOS arm64. Homebrew
`libomp 22.1.8` was already present; no system prerequisite was installed.

macOS needs OpenMP. If its native loader reports missing `libomp`, run:

```sh
brew install libomp
```

Native compatibility depends on the package's actual wheels and system libraries.
The installed CPython 3.13 wheel advertises macOS 26 arm64 and macOS 10.13 x86_64
tags; those tags alone do not prove every older Mac/runtime works. Linux is an
upstream supported platform but was not executed during this Mac repair.
Native Windows intentionally omits the package and retains the full TUI and
SQLite analytics. A supported Linux environment in WSL2 is the graph option;
WSL2 was not tested here. Do not treat successful SQLite fallback as native
cross-platform verification.

`GRAPH_BACKEND=auto|lite|off` controls startup. `off` never imports the native
library. `auto` and `lite` report actionable fallback diagnostics on failure.
`/graph` and the commands above run actual Cypher health checks without a model
call or API key. Ordinary agent startup stays lazy.

## Source-backed model and persistent synchronization

The versioned graph is stored beneath the configured user cache, beside the
SQLite snapshot, in `graph-v2.rdb`, outside the repository by default. A default
cache path is managed by `platformdirs`; `PL_CAPITAL_CACHE_DIR` can override it.
No cache or database belongs in source control.

Nodes use real SQLite keys:

- `Portfolio.id = portfolios.portfolio_id`.
- `Holding.id = holdings.holding_id`, with the original portfolio/security IDs.
- `Security.id = securities.security_id` and `Sector.id = sectors.sector_id`.
- `Table.name` and `Column.key = table.column` come from trusted introspection.

`Portfolio-HOLDS-Security` is preserved, with `holding_id` on each original edge.
`Portfolio-HAS_HOLDING-Holding-OF_SECURITY-Security` adds an explicit holding
path. `Security-IN_SECTOR-Sector` follows the nullable securities foreign key;
bonds without a sector remain represented through their holding. Schema edges
are `Table-HAS_COLUMN-Column` and `Table-REFERENCES-Table`, whose properties name
the real foreign-key columns. There is no inferred portfolio-to-sector edge.

One SQLite read transaction fingerprints the schema, foreign keys and actual
rows of all nine supplied tables with SHA-256, including graph version `v2`.
Changes made directly to SQLite therefore invalidate the graph even if the
CSV-import manifest remains unchanged. Relevant retrieval rechecks this identity.
A new fingerprint uses a new namespace, preserving prior snapshots and user
graph keys. Fixed parameterized `MERGE` operations, a completion marker written
last and explicit persistence make repeated starts/builds idempotent.
Interrupted ingestion retries its incomplete namespace. An interprocess lock
serializes native opening and synchronization; lock waits and socket timeouts
are separately capped at two seconds.

`graph build` synchronizes without clearing anything. `graph rebuild` clears and
recreates only the deterministic application namespace for the current SQLite
snapshot, under the same lock. Unrelated graph keys and SQLite remain intact.
If the native store cannot be opened, rebuild tries a fresh uniquely named
recovery store, keeps the damaged original bytes and records the new private
store name in an atomically replaced allowlisted cache pointer. It never removes
arbitrary directories or rewrites SQLite. Stop other clients before manual
rebuild to avoid temporarily observing an in-progress namespace. Old snapshot
namespaces and damaged stores are retained rather than automatically deleted.

## Retrieval and truthful provenance

A bounded SQLite entity catalogue first recognizes analytical terms and complete
known names. Stopwords, noise and short ambiguous spelling repairs are discarded.
At most one unique known token within one character edit or adjacent
transposition can repair a spelling; each repair is disclosed. Unknown and
ambiguous names are not invented. Simple counts and unrelated small talk do not
start native graph retrieval.

Fixed `GRAPH.RO_QUERY` traversals bind entity IDs and table lists as parameters;
question text is never concatenated into Cypher. They return selected entities,
explicit holding/security/sector paths, relevant columns and foreign-key joins.
Limits bound rows, 16 terms, 64 entities, per-query execution at 250 ms, and a
one-second cooperative read budget after startup. JSON context is kept below
18,000 characters for this fixed dataset. Native startup/cleanup have upstream
process waits and are not a hard one-second wall-clock guarantee. Startup and
complete retrieval duration are reported separately.

`used`/`graph_used` becomes true only after real matching entity or join evidence
is retrieved, rather than after a successful import. Provenance includes
`backend`/`graph_backend`, matched entities, `relevant_tables`, `relationship_paths`,
actual fixed queries and parameters, `snapshot_id`, `retrieval_ms`, normalizations
and `fallback_reason`. Missing evidence, budget exhaustion or transport failure
returns authoritative SQLite schema and a visible false graph-used status.

Health reports interpreter/package/platform information, schema version, snapshot
identity, synchronization state, per-label/per-edge counts and total node/edge
counts. It verifies the supplied snapshot counts, executes a sample read through
Holding, and checks that one real retrieval contributed context. For the supplied
dataset, verified counts were 13 portfolios, 95 holdings, 30 securities, 10 sectors,
9 tables and 80 columns; 95 each of HOLDS, HAS_HOLDING and OF_SECURITY, 25 IN_SECTOR,
80 HAS_COLUMN and 8 REFERENCES. Sample Cypher returned:

```text
Growth Equity Fund | holding 1 | AAPL | Technology
Growth Equity Fund | holding 2 | MSFT | Technology
Growth Equity Fund | holding 3 | NVDA | Technology
native_ready=true; graph_used=true
```

Tests distinguish actual native read/write, repeated starts, snapshot refresh,
namespace repair and planner-context-to-SQLite flow from injected missing-package,
native-loader and query failures. Native tests must run, not skip, to claim native
graph success. All quantitative outputs still execute SQLite/calculator tools.

## Upstream references and licenses

The installed package metadata declares Python >=3.12 and macOS/Linux classifiers,
and requires `redis>=4.5`, `falkordb[hiredis]>=1.8.0`, `psutil`, and `setuptools>38.0`.
Its Python wrapper uses BSD-3-Clause. The bundled FalkorDB engine has separate
SSPL v1 terms; installing the wrapper does not relicense that engine.

Primary sources: [FalkorDBLite documentation](https://github.com/FalkorDB/falkordblite),
[PyPI metadata](https://pypi.org/project/falkordblite/),
[wrapper license](https://github.com/FalkorDB/falkordblite/blob/master/LICENSE.txt),
[engine license](https://github.com/FalkorDB/FalkorDB/blob/master/LICENSE.txt).

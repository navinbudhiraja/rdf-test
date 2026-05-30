# CLAUDE.md — rdf-test

## Project Overview

Natural Language → SPARQL + SQL query engine over a university dataset. A user asks a question in plain English; the system uses Claude API to generate both a SPARQL query (for the Ontop VKG endpoint) and a SQL query (for DuckDB) in parallel, executes both, and displays results side-by-side. Also exposed as an MCP server so Claude can call it as a tool.

**Two datasets** are queryable, selected via `--dataset` on the CLI (default `university`) and via dedicated MCP tools:
- **university** — dual SPARQL + SQL, side-by-side (Ontop on :8080 + in-memory DuckDB).
- **hr** — the AcmeCorp multi-subsidiary HR knowledge graph, **SPARQL-only** (Ontop on :8081). HR data is modeled relationally (just like a real HRIS) and Ontop maps it to RDF; the rich SKOS/property-path graph is queried with SPARQL, so there is no hand-written SQL side. See "Second Dataset: AcmeCorp HR" below.

There is also a **Web Chat UI** for the HR dataset — a claude.ai-style conversational
interface backed by an `ask_hr` / `get_hr_schema` agent loop (the HR pipeline run
**in-process**, not via MCP) that renders answers as NL summaries + tables + charts.
See "Web Chat UI (HR)" below.

---

## Architecture

```
User Question (CLI / MCP / Slack)
    ↓
src/nl_translator.py  ← Claude API (parallel threads, prompt caching)
    ├→ SPARQL query
    └→ SQL query
         ↓                        ↓
src/sparql_executor.py     src/sql_executor.py
    ↓                              ↓
Ontop at localhost:8080    In-memory DuckDB
(reads university.ddb)     (loads data/university.sql)
    ↓                              ↓
         DataFrame          DataFrame
              ↓
    src/nl_query.py    (CLI, rich UI)
    src/mcp_server.py  (MCP tools for Claude Desktop)
    src/slack_bot.py   (Slack bot via Socket Mode)
```

The **HR Web Chat** runs the HR pipeline in-process (it does not spawn the MCP server;
`mcp_server.py` remains the MCP surface for Claude Desktop):

```
Browser (src/static/index.html — vanilla JS + Chart.js)
    ↓  POST /chat {session_id, message}
src/web.py (FastAPI)
    └→ src/chat_engine.py   Claude agent loop (Anthropic Messages API + extended
                            thinking, retries, decomposition, clarifying questions);
                            exposes only ask_hr / get_hr_schema to the model
                                ↓
       src/hr_query.py      ask_hr runs in-process (translate → SPARQL → Ontop :8081)
                            and returns {sparql, columns, rows, rowCount, error} —
                            structured data, no markdown round-trip
    ↓
NDJSON event stream (live): thinking_delta · tool_start · tool_result{card} ·
                            text_delta · done
    ↓
Browser renders incrementally: streaming reasoning → "Querying HR…" status →
                               table/chart cards → streaming summary bubble
```

The turn **streams** — `chat_engine.stream_turn` is an async generator and `POST /chat`
returns NDJSON, so the UI updates as thinking/queries/results/answer arrive rather than
blocking until the end. `run_turn` (used by tests) is a non-streaming wrapper over it.

---

## Key Source Files

| File | Role |
|------|------|
| `src/nl_translator.py` | Calls Claude API (`claude-sonnet-4-6`) with prompt caching; dataset-aware `translate(question, dataset)` runs the dataset's supported languages concurrently. Holds the university SPARQL/SQL prompts and the HR SPARQL prompt |
| `src/datasets.py` | Registry of datasets → label, supported languages, SPARQL endpoint, SQL source. CLI + MCP route through it |
| `src/nl_query.py` | CLI entry point; `--dataset {university,hr}` flag; language-aware display (side-by-side for university, SPARQL-only for hr) |
| `src/mcp_server.py` | FastMCP server. University tools: `ask_university`, `run_sql`, `get_schema`. HR tools: `ask_hr`, `run_sparql_hr`, `get_hr_schema` |
| `src/slack_bot.py` | Slack bot (Socket Mode); university dual pipeline (unchanged) |
| `src/web.py` | FastAPI backend for the HR Web Chat. `lifespan` only checks `ANTHROPIC_API_KEY`; `POST /chat` **streams** one agent turn as NDJSON over an in-memory per-`session_id` history; serves `static/index.html`. **Run with a single worker** (the `SESSIONS` dict is in-memory, not shared across workers) |
| `src/chat_engine.py` | Claude agent loop (raw Anthropic Messages API, `claude-sonnet-4-6`). `stream_turn` (async generator, streams thinking/tool/text events) + `run_turn` (non-streaming wrapper for tests). Extended thinking, `max_retries` + tool-level retry, decomposition into multiple `ask_hr` calls, clarifying questions. Defines the two HR tools (`HR_TOOLS`) and runs them in-process via `hr_query` (`ask_hr` wrapped in `asyncio.to_thread`); caches the system+tools prefix |
| `src/hr_query.py` | In-process HR pipeline for the web app: `run(question)` → translate → SPARQL → Ontop :8081 → `{sparql, columns, rows, rowCount, error}` (structured, no markdown). Holds the `get_hr_schema` text as `SCHEMA`. Blocking — callers wrap it in `asyncio.to_thread` |
| `src/static/index.html` | Single-file chat UI: vanilla JS + Chart.js (CDN, no build). Summary bubble, collapsible "Show reasoning", per-result table with **Table\|Chart** toggle, "View SPARQL" |
| `src/sparql_executor.py` | HTTP POST to an Ontop SPARQL endpoint (`execute(sparql, endpoint=…)`, default :8080); returns pandas DataFrame |
| `src/sql_executor.py` | Executes SQL against in-memory DuckDB loaded from `data/university.sql` (university only); in-memory avoids JDBC file-lock conflict with Ontop |
| `ontop/university.obda` / `.ttl` / `database.properties` | University OBDA mappings, ontology, JDBC config (→ `university.ddb`) |
| `ontop/hr.obda` / `hr.ttl` / `hr_database.properties` | HR OBDA mappings (rebuild the full RDF graph from the HR tables), HR TBox, JDBC config (→ `hr.ddb`) |
| `data/university.sql` / `data/hr.sql` | Relational schema + seed data for each dataset (`hr.sql` is generated, see below) |
| `hr-dataset/` | The source HR dataset (9 Turtle files), example queries, and tests — see "Second Dataset" |
| `hr-dataset/build_relational.py` | One-off: loads the HR Turtle via rdflib and writes `data/hr.sql` (DDL + INSERTs). Source of truth = the Turtle |
| `hr-dataset/tests/verify_ontop.py` | Round-trip test: runs every `queries/*.rq` against the rdflib oracle AND the HR Ontop endpoint and asserts equality |
| `hr-dataset/tests/test_nl_translation.py` | End-to-end test of the HR SPARQL **prompt**: NL question → `translate()` → Ontop, asserts results. Run after editing `_HR_SPARQL_SYSTEM` |
| `hr-dataset/tests/load_and_query.py` | Oracle self-test: loads the Turtle in rdflib, runs `queries/*.rq` against `expected_results.md`, and runs SHACL shapes. No Ontop needed |
| `doc/architecture.md` | Mermaid system diagrams (entry points, engine, data layer, Slack/MCP integration) |
| `doc/hr_sparql_prompt_design.md` | Design notes for `_HR_SPARQL_SYSTEM`: what was pulled from TBox / OBDA / gold queries, and which Ontop 5.5.0 constraints shaped it |
| `setup.sh` | One-time setup: downloads Ontop v5.5.0 CLI + DuckDB JDBC; builds `university.ddb` and `hr.ddb` |
| `start_ontop.sh` | `./start_ontop.sh [university\|hr]` — starts the chosen Ontop endpoint (university :8080, hr :8081). Scopes its `pkill` to the dataset's OBDA filename so the two endpoints coexist |
| `query.sh` / `query_hr.sh` | Thin wrappers around `python src/nl_query.py [--dataset hr] "…"` |
| `start_web.sh` | `./start_web.sh [port]` — starts the HR Web Chat (uvicorn) using the project venv; warns if the HR endpoint (:8081) isn't up. Default port 8000 |

---

## Data Layer

### Relational Schema (`data/university.sql`)

| Table | Columns | Rows |
|-------|---------|------|
| `student` | s_id, fname, lname | 10 |
| `academic` | a_id, fname, lname, position | 6 |
| `course` | c_id, title | 5 |
| `teaching` | a_id, c_id | junction |
| `course_registration` | s_id, c_id | junction |

`academic.position` codes: `1`=FullProfessor, `2`=AssociateProfessor, `3`=AssistantProfessor, `9`=PostDoc

### RDF Ontology (`ontop/university.ttl`)

- `voc:Person` → `voc:Student`, `voc:AcademicMember`
- `voc:AcademicMember` → `voc:FullProfessor`, `voc:AssociateProfessor`, `voc:AssistantProfessor`, `voc:PostDoc`
- `voc:Course`
- Properties: `foaf:firstName`, `foaf:lastName`, `voc:courseTitle`, `voc:teaches`, `voc:isEnrolledIn`, `voc:isTaughtBy`
- IRI patterns: `:student/{s_id}`, `:academic/{a_id}`, `:course/{c_id}`

---

## Second Dataset: AcmeCorp HR (SPARQL-only)

A synthetic multinational HR knowledge graph: **AcmeCorp** with three subsidiaries
(**AcmeUK, AcmeDE, AcmeUS**). Each subsidiary has its own LOCAL job-title vocabulary;
all local roles map via SKOS (`closeMatch`/`broadMatch`) to a single GLOBAL role catalog,
which is anchored to real ESCO/ISCO occupations. Demonstrates cross-subsidiary role
reconciliation (Role / Post / Membership separation, graded SKOS mappings, mapping
provenance, ESCO alignment).

**Source of truth:** the 9 Turtle files in `hr-dataset/` (`01_ontology.ttl` … `09_shapes.shacl.ttl`).
`hr-dataset/build_relational.py` converts them into the relational schema `data/hr.sql`
(loaded in memory with a fix that merges multi-line string literals — the shipped Turtle
splits some descriptions across adjacent literals, which is invalid Turtle).

**Why relational + Ontop (not native RDF):** in the real-world use case the HR data is
genuinely relational, so a relational source + OBDA is representative of production.
Ontop rewrites SPARQL → SQL against the HR tables; the Turtle is never read at runtime.

**Why SPARQL-only:** the dataset's value is its SKOS property-path / graph structure,
which is awkward in hand-written SQL, so the HR pipeline generates only SPARQL.

### HR relational schema (`data/hr.sql`, 12 tables)

`organization`, `org_label`, `seniority_level`, `job_family`, `global_role`,
`local_role`, `role_mapping`, `mapping_agent`, `esco_anchor`, `person`, `post`,
`membership`. Codes/IRIs are chosen so `ontop/hr.obda` reconstructs the exact original
IRIs (e.g. `acmeG:SoftwareEngineerL4`, `acmeUK:SeniorSoftwareEngineer`, `p:alice_01`).
n-ary `org:Membership` intervals are rebuilt as minted `interval`/`instant` IRIs.

### RDF Ontology (`ontop/hr.ttl`)

The HR TBox is deliberately small — it only declares AcmeCorp's **custom**
classes and properties. The bulk of the HR vocabulary comes from standard
ontologies (`org:`, `foaf:`, `skos:`, `prov:`, `time:`) that aren't redeclared
here; they appear directly in the OBDA mapping targets.

- Custom classes (all in `acme:`): `Subsidiary` (⊑ `org:FormalOrganization`),
  `GlobalRole` and `LocalRole` (both ⊑ `org:Role`, `skos:Concept`), `JobFamily`
  (⊑ `skos:Concept`), `SeniorityLevel`, `MappingActivity` (⊑ `prov:Activity`).
- Custom properties: `acme:scopedTo` (LocalRole → Subsidiary),
  `acme:hasJobFamily`, `acme:hasSeniorityLevel`, `acme:viaPost`
  (Membership → Post); datatypes `acme:levelOrdinal`, `acme:confidence`,
  `acme:mappingMethod`, `acme:reviewStatus`.
- Standard-vocab classes used in queries but **not** in `hr.ttl` (they live in
  `hr.obda` targets, so the prompt has to know them explicitly):
  `org:Post`, `org:Membership`, `foaf:Person`, `skos:Concept`,
  `prov:Activity`, `time:Interval`, `time:Instant`.
- IRI prefixes (from `hr.obda`):
  `acme:` (vocabulary), `acmeG:` (global roles), `acmeUK:` / `acmeDE:` / `acmeUS:`
  (per-subsidiary local roles), `p:` (persons), `post:` (posts).
- IRI patterns reconstructed by the OBDA: `acmeG:{code}`, `acmeUK:{code}` /
  `acmeDE:{code}` / `acmeUS:{code}`, `p:{person_code}`, `post:{post_code}`;
  membership intervals are minted as `acme:interval/{id}` / `acme:instant/{id}`.

### What's in the data

- ~41 people, ~41 posts, ~21 global roles, ~48 local roles (split across the 3
  subsidiaries), ~47 SKOS mappings, ~24 ESCO anchors, 4 organizations.
- Title styles per subsidiary: AcmeUK uses "Senior X / Lead Y / Head of Z"
  (`@en-GB`); AcmeDE uses German titles with II/III/IV seniority suffixes
  (`@de`, plus `@en` on org labels); AcmeUS uses LX ladder levels + "VP /
  Director" (`@en-US`). Global roles are `@en`.
- Designed to answer: cross-subsidiary role equivalence, ESCO/skill traversal,
  reporting lines via `post → reportsTo`, mappings needing review (low
  confidence or missing approval), open postings (Post with no current
  Membership), unmapped local roles, people-by-seniority/job-family.
- Deliberate "gotchas" (so review/exception queries return non-empty results):
  one AcmeDE role is intentionally unmapped; two mappings have
  `acme:confidence < 0.7`; one person holds an open Post with no Membership.
  See `hr-dataset/README.md` for the full list.

### Verification (round-trip correctness)

Three layers of tests, in order of what they catch:

- `hr-dataset/tests/load_and_query.py` — validates the **oracle**. Loads the
  Turtle into rdflib, runs `queries/*.rq` against `expected_results.md`, and
  runs the SHACL shapes. No Ontop needed.
- `hr-dataset/tests/verify_ontop.py` — validates the **Ontop mappings**. Globs
  `hr-dataset/queries/*.rq`, runs each against both the rdflib oracle and the
  HR Ontop endpoint (:8081), and asserts the result sets match
  (numeric/datetime canonicalized, order-independent). Data-driven: drop a new
  `NN_name.rq` into `hr-dataset/queries/` and it's picked up automatically.
- `hr-dataset/tests/test_nl_translation.py` — validates the **HR SPARQL
  prompt**. Sends NL questions through `translate()` to Ontop and asserts the
  results. Run this after editing `_HR_SPARQL_SYSTEM` in `nl_translator.py`;
  the `verify_ontop` tests above don't cover prompt regressions because they
  only test hand-written queries.

---

## Environment

`.env` (copy from `.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...   # Bot User OAuth Token from api.slack.com
SLACK_APP_TOKEN=xapp-...   # App-Level Token (Socket Mode) from api.slack.com
```

---

## How to Run

### One-time setup
```bash
bash setup.sh
pip install -r requirements.txt
```

### Start Ontop SPARQL endpoint(s) (required for SPARQL queries)
```bash
./start_ontop.sh university   # http://localhost:8080/  — keep terminal open
./start_ontop.sh hr           # http://localhost:8081/  — separate terminal
```
The two are independent (different ports, different `.ddb` files); run both in
parallel to query both datasets concurrently.

### CLI query
```bash
# University (dual SPARQL + SQL, side-by-side)
python src/nl_query.py "Which professors teach more than one course?"
bash query.sh "Which students are enrolled in AI?"

# HR (SPARQL-only)
python src/nl_query.py --dataset hr "Which employees are software engineers across all subsidiaries?"
bash query_hr.sh "Show the reporting chain for Alice Chen"
```

### MCP server
```bash
python src/mcp_server.py
```

### Web Chat UI (HR)
Requires the HR Ontop endpoint (`./start_ontop.sh hr`) and `ANTHROPIC_API_KEY`.
```bash
./start_web.sh                       # uses the venv; open http://localhost:8000/
./start_web.sh 9000                  # optional: choose a different port
# (equivalent to: uvicorn web:app --app-dir src — single worker)
```
A claude.ai-style chat over the HR dataset. The backend (`src/web.py`) runs an
`ask_hr` / `get_hr_schema` agent loop (`src/chat_engine.py`) whose tools execute the
HR pipeline in-process via `src/hr_query.py` — no MCP subprocess. The model plans with
extended thinking, decomposes complex questions into multiple `ask_hr` calls, retries
transient failures, and asks clarifying questions when ambiguous. Each answer is an
interpretive NL summary plus rendered tables/charts (`ask_hr` returns structured data
directly). See "Web Chat UI (HR)" under the architecture notes.
**One worker only** — the in-memory session state is not shared across workers.

### Slack bot
```bash
python src/slack_bot.py
# Connects to Slack via Socket Mode (no public URL needed)
# DM the bot or @mention it in a channel
```

---

## Claude API Usage

- **Model:** `claude-sonnet-4-6`
- **Prompt caching:** Both SPARQL and SQL system prompts use `cache_control: {"type": "ephemeral"}` — system prompts are large (full ontology + schema + examples) and cached to reduce latency/cost
- **Parallel generation:** `ThreadPoolExecutor(max_workers=2)` runs SPARQL and SQL translation concurrently
- **Temperature:** 0 (deterministic output)
- **Max tokens:** 1024

System prompts are embedded directly in `src/nl_translator.py` (not loaded from files) — edit them there when updating ontology context or query examples.

---

## Development Notes

### Testing
- **ALWAYS run the tests after making a change** — don't stop at import/syntax
  checks. Run what's relevant to what you touched, and report results honestly
  (pass/fail counts, and which failures pre-date your change).
- Automated tests live in `hr-dataset/tests/` — see "Verification" above for the
  three-layer breakdown (oracle / Ontop / NL-prompt). The university side has
  no automated tests; all testing there is manual via CLI or MCP.
- How to run them (they need the project venv + `.env` key on the env, and the
  Ontop tests need the HR endpoint up):
  ```bash
  ./start_ontop.sh hr                       # for verify_ontop / test_nl_translation
  set -a; source .env; set +a               # tests read ANTHROPIC_API_KEY from the env
  cd hr-dataset/tests
  PYTHONPATH=../../src ../../.venv/bin/python verify_ontop.py        # Ontop mappings
  PYTHONPATH=../../src ../../.venv/bin/python test_nl_translation.py # HR prompt (LLM — mildly flaky)
  PYTHONPATH=../../src ../../.venv/bin/python load_and_query.py      # rdflib oracle + SHACL
  ```
- **Coverage gap to be aware of:** none of the three tests import `web.py` /
  `chat_engine.py` / `hr_query.py`. After changing the HR web chat, the tests
  above only confirm the pipeline beneath it is intact — validate the web layer
  itself with an end-to-end `chat_engine.run_turn(messages)` call (key + HR
  endpoint required), not just the test suite.
- `test_nl_translation.py` drives a live LLM, so an occasional off-by-a-row
  failure is prompt nondeterminism, not necessarily a regression — re-run before
  concluding you broke something.

### Ontop runtime
- **Heap**: the default 512 MB OOMs on the HR rewriter. `start_ontop.sh`
  exports `ONTOP_JAVA_ARGS="-Xmx2g -XX:+UseG1GC -XX:MaxGCPauseMillis=200"` —
  don't strip it.
- **Ontop 5.5.0 SPARQL quirks** that shaped the HR prompt and OBDA:
  - `lang()` returns lowercased tags. Filter on `"en-gb" / "de" / "en-us" / "en"`,
    not `"en-GB"`.
  - No arbitrary property paths in OBDA mapping targets.
  - No meta-mappings (a mapping target can't reference another mapping).
- **Dual endpoints coexist**: `start_ontop.sh` scopes its `pkill` to the
  dataset's OBDA filename, so `start_ontop.sh hr` won't kill an existing
  university endpoint (and vice versa). Don't "simplify" the pkill — DuckDB
  takes an exclusive lock per `.ddb`, but the two datasets have separate files.
- If Ontop is not running, SPARQL queries fail with a helpful error; university
  SQL still works (it goes through in-memory DuckDB, not Ontop).

### Data files
- `university.ddb` and `hr.ddb` (repo root) are the binary DuckDB files Ontop
  reads. Both are regenerated by `setup.sh`.
- `data/university.sql` is the source of truth for the university schema/seed.
- `data/hr.sql` is **generated** from the 9 Turtle files in `hr-dataset/` by
  `hr-dataset/build_relational.py` — edit the Turtle, not `hr.sql`.
- **In-memory DuckDB** in `sql_executor.py` is intentional: avoids file-lock
  conflicts when Ontop's JDBC process holds `university.ddb` open.

### Iterating on prompts
- SPARQL/SQL system prompts are embedded directly in `src/nl_translator.py`
  (not loaded from files) — edit them there.
- HR prompt workflow:
  1. `./start_ontop.sh hr` (in another terminal; endpoint on :8081)
  2. Edit `_HR_SPARQL_SYSTEM` in `src/nl_translator.py`
  3. `python hr-dataset/tests/test_nl_translation.py`
- See `doc/hr_sparql_prompt_design.md` for what each section of the prompt
  contributes and which Ontop/gold-query constraints shaped it.

### Slack
- Slack bot uses Socket Mode (no public URL or port forwarding); university
  pipeline only; requires `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`.
  See `README.md` for the one-time Slack App setup.

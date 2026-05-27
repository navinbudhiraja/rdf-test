# CLAUDE.md — rdf-test

## Project Overview

Natural Language → SPARQL + SQL query engine over a university dataset. A user asks a question in plain English; the system uses Claude API to generate both a SPARQL query (for the Ontop VKG endpoint) and a SQL query (for DuckDB) in parallel, executes both, and displays results side-by-side. Also exposed as an MCP server so Claude can call it as a tool.

**Two datasets** are queryable, selected via `--dataset` on the CLI (default `university`) and via dedicated MCP tools:
- **university** — dual SPARQL + SQL, side-by-side (Ontop on :8080 + in-memory DuckDB).
- **hr** — the AcmeCorp multi-subsidiary HR knowledge graph, **SPARQL-only** (Ontop on :8081). HR data is modeled relationally (just like a real HRIS) and Ontop maps it to RDF; the rich SKOS/property-path graph is queried with SPARQL, so there is no hand-written SQL side. See "Second Dataset: AcmeCorp HR" below.

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

---

## Key Source Files

| File | Role |
|------|------|
| `src/nl_translator.py` | Calls Claude API (`claude-sonnet-4-6`) with prompt caching; dataset-aware `translate(question, dataset)` runs the dataset's supported languages concurrently. Holds the university SPARQL/SQL prompts and the HR SPARQL prompt |
| `src/datasets.py` | Registry of datasets → label, supported languages, SPARQL endpoint, SQL source. CLI + MCP route through it |
| `src/nl_query.py` | CLI entry point; `--dataset {university,hr}` flag; language-aware display (side-by-side for university, SPARQL-only for hr) |
| `src/mcp_server.py` | FastMCP server. University tools: `ask_university`, `run_sql`, `get_schema`. HR tools: `ask_hr`, `run_sparql_hr`, `get_hr_schema` |
| `src/slack_bot.py` | Slack bot (Socket Mode); university dual pipeline (unchanged) |
| `src/sparql_executor.py` | HTTP POST to an Ontop SPARQL endpoint (`execute(sparql, endpoint=…)`, default :8080); returns pandas DataFrame |
| `src/sql_executor.py` | Executes SQL against in-memory DuckDB loaded from `data/university.sql` (university only); in-memory avoids JDBC file-lock conflict with Ontop |
| `ontop/university.obda` / `.ttl` / `database.properties` | University OBDA mappings, ontology, JDBC config (→ `university.ddb`) |
| `ontop/hr.obda` / `hr.ttl` / `hr_database.properties` | HR OBDA mappings (rebuild the full RDF graph from the HR tables), HR TBox, JDBC config (→ `hr.ddb`) |
| `data/university.sql` / `data/hr.sql` | Relational schema + seed data for each dataset (`hr.sql` is generated, see below) |
| `hr-dataset/` | The source HR dataset (9 Turtle files), example queries, and tests — see "Second Dataset" |
| `hr-dataset/build_relational.py` | One-off: loads the HR Turtle via rdflib and writes `data/hr.sql` (DDL + INSERTs). Source of truth = the Turtle |
| `hr-dataset/tests/verify_ontop.py` | Round-trip test: runs every `queries/*.rq` against the rdflib oracle AND the HR Ontop endpoint and asserts equality |
| `setup.sh` | One-time setup: downloads Ontop v5.5.0 CLI + DuckDB JDBC; builds `university.ddb` and `hr.ddb` |
| `start_ontop.sh` | `./start_ontop.sh [university\|hr]` — starts the chosen Ontop endpoint (university :8080, hr :8081) |

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

### Verification (round-trip correctness)

`hr-dataset/tests/verify_ontop.py` is **data-driven**: it globs `hr-dataset/queries/*.rq`,
runs each against the **rdflib oracle** (original Turtle) and the **HR Ontop endpoint**
(:8081), and asserts the result sets match (numeric/datetime canonicalized,
order-independent). Adding a test later = drop a new `NN_name.rq` into
`hr-dataset/queries/` — it's picked up automatically; the oracle computes the expected
answer. (`hr-dataset/tests/load_and_query.py` separately validates the oracle itself
against `expected_results.md` via rdflib, and runs the SHACL shapes.)

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

### Start Ontop SPARQL endpoint (required for SPARQL queries)
```bash
bash start_ontop.sh
# Runs on http://localhost:8080/ — keep terminal open
```

### CLI query
```bash
python src/nl_query.py "Which professors teach more than one course?"
# Or via wrapper:
bash query.sh "Which students are enrolled in AI?"
```

### MCP server
```bash
python src/mcp_server.py
```

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

- **No automated tests** — all testing is manual via CLI or MCP tool invocation
- **In-memory DuckDB** in `sql_executor.py` is intentional: avoids file-lock conflicts when Ontop's JDBC process holds `university.ddb` open
- If Ontop is not running, SPARQL queries fail with a helpful error; SQL still works
- `university.ddb` is the binary DuckDB file used by Ontop; `data/university.sql` is the source of truth for the schema and seed data
- Slack bot uses Socket Mode — no public URL or port forwarding needed; requires `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`

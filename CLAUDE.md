# CLAUDE.md — rdf-test

## Project Overview

Natural Language → SPARQL + SQL query engine over a university dataset. A user asks a question in plain English; the system uses Claude API to generate both a SPARQL query (for the Ontop VKG endpoint) and a SQL query (for DuckDB) in parallel, executes both, and displays results side-by-side. Also exposed as an MCP server so Claude can call it as a tool.

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
| `src/nl_translator.py` | Calls Claude API (`claude-sonnet-4-6`) with prompt caching; runs SPARQL and SQL generation concurrently via `ThreadPoolExecutor` |
| `src/nl_query.py` | CLI entry point; orchestrates translate → execute → display with `rich` panels/tables |
| `src/mcp_server.py` | FastMCP server exposing 3 tools: `ask_university`, `run_sql`, `get_schema` |
| `src/slack_bot.py` | Slack bot (Socket Mode); listens for @mentions and DMs, runs the full NL→SPARQL+SQL pipeline, posts results as Slack blocks |
| `src/sparql_executor.py` | HTTP POST to Ontop SPARQL endpoint at `http://localhost:8080/sparql`; returns pandas DataFrame |
| `src/sql_executor.py` | Executes SQL against in-memory DuckDB loaded from `data/university.sql`; in-memory avoids JDBC file-lock conflict with Ontop |
| `ontop/university.obda` | OBDA mappings: 13 rules converting SQL rows → RDF triples |
| `ontop/university.ttl` | OWL 2 QL ontology (Person, Student, AcademicMember subclasses, Course, teaches, isEnrolledIn) |
| `ontop/database.properties` | Ontop JDBC config pointing at `university.ddb` |
| `data/university.sql` | Relational schema + seed data (5 tables, ~30 rows total) |
| `setup.sh` | One-time setup: downloads Ontop v5.5.0 CLI, DuckDB JDBC driver, creates `university.ddb` |
| `start_ontop.sh` | Starts Ontop SPARQL endpoint in foreground on port 8080 |

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

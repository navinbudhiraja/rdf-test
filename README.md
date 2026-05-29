# NL → SPARQL (+ SQL) Engine (Ontop VKG)

A CLI tool that takes a natural language question and generates a SPARQL query (and, where applicable, a SQL query) using Claude, executes them against an Ontop VKG endpoint, and displays the results. Two datasets are supported:

- **university** — dual SPARQL + SQL, displayed side-by-side (Ontop on :8080 + in-memory DuckDB).
- **hr** — the AcmeCorp multi-subsidiary HR knowledge graph, SPARQL-only (Ontop on :8081). See [`hr-dataset/README.md`](hr-dataset/README.md) for the data model.

```
University:  "Which professors teach more than one course?"
                ├──► Claude ──► SPARQL ──► Ontop :8080 ──► DuckDB ──► table
                └──► Claude ──► SQL    ──► DuckDB (direct)        ──► table

HR:          "Show the reporting chain for Alice Chen"
                └──► Claude ──► SPARQL ──► Ontop :8081 ──► DuckDB ──► table
```

## Prerequisites

- Python 3.10+
- Java 11+ (required by Ontop CLI)
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

```bash
# 1. Clone / enter the project
cd rdf-test

# 2. Run setup (downloads Ontop CLI + DuckDB JDBC driver, builds university.ddb and hr.ddb)
./setup.sh

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Create your .env file from the example and fill in your keys
cp .env.example .env
```

Edit `.env` and set at minimum:
```
ANTHROPIC_API_KEY=sk-ant-...
```

## Running

### Step 1 — Start the Ontop SPARQL endpoint(s) (keep each terminal open)

```bash
./start_ontop.sh university   # http://localhost:8080/  (SPARQL browser UI)
./start_ontop.sh hr           # http://localhost:8081/  (run in a separate terminal)
```

The two endpoints are independent; start whichever you need (or both in parallel). `start_ontop.sh` exports the heap settings Ontop needs to avoid OOM on the HR rewriter — prefer it over invoking the Ontop CLI directly.

### Step 2 — Ask questions (in a separate terminal)

```bash
# University (dual SPARQL + SQL)
python src/nl_query.py "List all students"
python src/nl_query.py "Which full professors teach more than one course?"
python src/nl_query.py "How many students are enrolled in each course?"

# HR (SPARQL-only) — pass --dataset hr, or use the wrapper
python src/nl_query.py --dataset hr "Which employees are software engineers across all subsidiaries?"
./query_hr.sh "Show the reporting chain for Alice Chen"
./query_hr.sh "Which role mappings need review?"
```

## Web Chat (HR)

A claude.ai-style chat interface for the **HR** dataset, served from a small FastAPI
backend. Ask questions in plain English and get back a natural-language summary plus
rendered **tables and charts**. Under the hood it drives the project's MCP server
(`ask_hr` / `get_hr_schema` only) — the model plans with step-by-step thinking,
breaks complex questions into multiple `ask_hr` queries, retries transient failures,
and asks clarifying questions when a request is ambiguous.

Start the HR Ontop endpoint and the web server (two terminals):

```bash
./start_ontop.sh hr                  # http://localhost:8081/  (keep open)
./start_web.sh                       # http://localhost:8000/  (uses the venv; single worker)
```

(`start_web.sh` takes an optional port, e.g. `./start_web.sh 9000`, and is just a
wrapper around `uvicorn web:app --app-dir src` using the project's `.venv`.)

Then open <http://localhost:8000/> and chat. Requires `ANTHROPIC_API_KEY` in `.env`.
Each result card shows the data as a table with a **Table / Chart** toggle (bar chart
when there's a category + a numeric column) and a collapsible **View SPARQL**; a
**Show reasoning** disclosure reveals the model's thinking.

> Run a **single** worker: there is one shared MCP subprocess and in-memory
> conversation state, so multiple workers would not share sessions.

## Slack Bot

The Slack bot lets anyone in your workspace ask natural language questions by DMing the bot or @mentioning it in a channel. It uses Socket Mode — no public URL or port forwarding needed.

### First-time Slack App setup (admin only — do this once per workspace)

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. **Enable Socket Mode** (Settings → Socket Mode → toggle on) → generate an App-Level Token with scope `connections:write` → copy the `xapp-...` token
3. **Add Bot Token Scopes** (Features → OAuth & Permissions → Bot Token Scopes):
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
4. **Subscribe to bot events** (Features → Event Subscriptions → toggle on → Subscribe to bot events):
   - `app_mention`
   - `message.im`
5. **Enable Messages Tab** (Features → App Home → Messages Tab → toggle on "Allow users to send messages")
6. **Install to workspace** (Settings → Install App → Install to Workspace → Allow) → copy the `xoxb-...` Bot Token

### Running the bot (each developer, on their own machine)

Add the two tokens to your `.env`:
```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

Start Ontop (required for SPARQL results — SQL works without it). The Slack bot is **university-only**, so only the university endpoint is needed:
```bash
./start_ontop.sh university
```

Start the bot:
```bash
python src/slack_bot.py
```

The bot is online as long as this process is running. In Slack:
- **DM:** open a DM with University Bot and type your question
- **Channel:** `@University Bot which professors teach more than one course?`

> **Note:** The `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are shared across your team — get them from whoever set up the Slack App, or from https://api.slack.com/apps if you have access.

---

## Datasets

### University

From the [Ontop VKG tutorial](https://ontop-vkg.org/tutorial/):

| Table | Description |
|---|---|
| `student` | 10 students with first/last name |
| `academic` | 6 staff: 2 Full Professors, 1 Associate, 1 Assistant, 2 PostDocs |
| `course` | 5 courses (Information Systems, Software Engineering, …) |
| `teaching` | Which academic teaches which course |
| `course_registration` | Which student is enrolled in which course |

### AcmeCorp HR

A synthetic multinational HR knowledge graph with three subsidiaries (AcmeUK, AcmeDE, AcmeUS). Each subsidiary uses its own local job-title vocabulary; all local roles map via SKOS (`closeMatch`/`broadMatch`) to a single global role catalog, which is anchored to real ESCO/ISCO occupations.

~41 people, ~21 global roles, ~48 local roles, ~47 SKOS mappings, ~24 ESCO anchors across 4 organizations. Designed to demonstrate cross-subsidiary role reconciliation, ESCO/skill traversal, reporting lines, and mapping-quality queries.

The Turtle is the source of truth — `hr-dataset/build_relational.py` converts the 9 `.ttl` files into `data/hr.sql`, and `ontop/hr.obda` rebuilds the same RDF graph from those tables. See [`hr-dataset/README.md`](hr-dataset/README.md) for the full data dictionary.

## Architecture

| Component | Role |
|---|---|
| `src/nl_translator.py` | Calls Claude API (parallel threads, prompt caching) to generate SPARQL + SQL from NL — dataset-aware |
| `src/datasets.py` | Registry of datasets → label, supported languages, SPARQL endpoint, SQL source |
| `src/sparql_executor.py` | HTTP POST to an Ontop SPARQL endpoint, parses JSON results |
| `src/sql_executor.py` | In-memory DuckDB loaded from `data/university.sql`, executes SQL directly (university only) |
| `src/nl_query.py` | CLI entry point; `--dataset {university,hr}` flag |
| `src/mcp_server.py` | MCP server. University tools: `ask_university`, `run_sql`, `get_schema`. HR tools: `ask_hr`, `run_sparql_hr`, `get_hr_schema` |
| `src/slack_bot.py` | Slack bot (Socket Mode) — DMs and @mentions trigger the university NL→SPARQL+SQL pipeline |
| `src/web.py` · `src/chat_engine.py` · `src/mcp_client.py` · `src/hr_markdown.py` · `src/static/index.html` | HR **Web Chat**: FastAPI `/chat` → Claude agent loop → persistent MCP client (`ask_hr`/`get_hr_schema`) → markdown parser; vanilla-JS + Chart.js UI |
| `ontop/university.obda` / `.ttl` | University OBDA mappings + OWL 2 QL ontology |
| `ontop/hr.obda` / `hr.ttl` | HR OBDA mappings + custom TBox (built on `org:`, `foaf:`, `skos:`, `prov:`, `time:`) |
| `data/university.sql` / `data/hr.sql` | Source data per dataset (`hr.sql` is generated from `hr-dataset/*.ttl`) |
| `hr-dataset/` | Source HR Turtle files, gold queries, and tests |
| `start_ontop.sh` | `./start_ontop.sh [university\|hr]` — starts the chosen endpoint on :8080 / :8081 |
| `query.sh` / `query_hr.sh` | Thin CLI wrappers for the two datasets |

## How it works

1. **Ontop VKG** sits on top of the DuckDB files and exposes each as a SPARQL endpoint. When you send a SPARQL query, Ontop rewrites it to SQL using the OBDA mapping rules and executes it against DuckDB transparently.

2. **Claude API** receives the natural language question with the full ontology/schema as cached context and returns a query in the target language. For the university dataset, SPARQL and SQL translations run concurrently.

3. **Results**: for university, SPARQL and SQL outputs are displayed side by side so you can compare them. For HR, only SPARQL is generated and a single results table is shown.

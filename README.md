# NL → SPARQL + SQL Engine (Ontop VKG)

A CLI tool that takes a natural language question, generates both a SPARQL query and a SQL query using Claude, executes them against the university dataset, and displays the results as side-by-side tables.

```
User: "Which professors teach more than one course?"
         │
         ├──► Claude API ──► SPARQL ──► Ontop VKG endpoint ──► DuckDB ──► table
         └──► Claude API ──► SQL    ──► DuckDB (direct)           ──► table
```

## Prerequisites

- Python 3.10+
- Java 11+ (required by Ontop CLI)
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

```bash
# 1. Clone / enter the project
cd rdf-test

# 2. Run setup (downloads Ontop CLI, DuckDB JDBC driver, creates university.ddb)
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

### Step 1 — Start the Ontop SPARQL endpoint (keep this terminal open)

```bash
./ontop-cli/ontop endpoint \
    -m ontop/university.obda \
    -t ontop/university.ttl \
    -p ontop/database.properties \
    --cors-allowed-origins='*'
```

The SPARQL browser UI is at http://localhost:8080/

### Step 2 — Ask questions (in a separate terminal)

```bash
python src/nl_query.py "List all students"
python src/nl_query.py "Which full professors teach more than one course?"
python src/nl_query.py "Who is enrolled in Database Systems?"
python src/nl_query.py "How many students are enrolled in each course?"
python src/nl_query.py "Which students share a course with a PostDoc?"
```

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

Start Ontop (required for SPARQL results — SQL works without it):
```bash
./start_ontop.sh
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

## Dataset

The **university dataset** (from the [Ontop VKG tutorial](https://ontop-vkg.org/tutorial/)) contains:

| Table | Description |
|---|---|
| `student` | 10 students with first/last name |
| `academic` | 6 staff: 2 Full Professors, 1 Associate, 1 Assistant, 2 PostDocs |
| `course` | 5 courses (Information Systems, Software Engineering, …) |
| `teaching` | Which academic teaches which course |
| `course_registration` | Which student is enrolled in which course |

## Architecture

| Component | Role |
|---|---|
| `src/nl_translator.py` | Calls Claude API (parallel threads) to generate SPARQL + SQL from NL |
| `src/sparql_executor.py` | HTTP POST to Ontop SPARQL endpoint, parses JSON results |
| `src/sql_executor.py` | In-memory DuckDB loaded from `data/university.sql`, executes SQL directly |
| `src/nl_query.py` | CLI entry point, orchestrates translation + execution + display |
| `src/mcp_server.py` | MCP server exposing `ask_university`, `run_sql`, `get_schema` tools to Claude Desktop |
| `src/slack_bot.py` | Slack bot (Socket Mode) — DMs and @mentions trigger the full NL→SPARQL+SQL pipeline |
| `ontop/university.obda` | OBDA mappings: SQL → RDF triples |
| `ontop/university.ttl` | OWL 2 QL ontology (classes + properties) |
| `data/university.sql` | Source data (CREATE TABLE + INSERT) |

## How it works

1. **Ontop VKG** sits on top of the DuckDB file and exposes it as a SPARQL endpoint. When you send a SPARQL query, Ontop rewrites it to SQL using the OBDA mapping rules and executes it against DuckDB transparently.

2. **Claude API** receives the natural language question with the full ontology/schema as cached context and returns a query in the target language. Both translations run concurrently.

3. **Results** are displayed side by side so you can compare the SPARQL and SQL outputs for the same question.

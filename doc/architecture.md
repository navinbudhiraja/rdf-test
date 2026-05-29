# Architecture

End-to-end picture of the system as it stands today: two datasets (university dual
SPARQL+SQL, HR SPARQL-only), entry points (CLI / MCP / Slack / HR Web Chat), one shared
query engine, two Ontop endpoints. The **HR Web Chat** is layered on top of the MCP
server (it is an MCP *client*) rather than calling the engine directly — see
"HR Web Chat" below.

## System Overview

```mermaid
flowchart TB
    subgraph SLACK["☁️  Slack Cloud"]
        SU["User in Slack<br/>(channel / DM)"]
        SS["Slack Servers"]
        SU <--> SS
    end

    subgraph DESKTOP["🖥️  Claude Desktop"]
        CD["Claude Desktop<br/>(MCP client)"]
    end

    subgraph CLOUD["☁️  External APIs"]
        CA["Anthropic Claude API<br/>claude-sonnet-4-6<br/>(prompt caching)"]
    end

    subgraph LAPTOP["💻  Your Laptop"]

        subgraph ENTRY["Entry Points"]
            CLI["CLI<br/>src/nl_query.py<br/>--dataset {university,hr}"]
            MCP["MCP Server<br/>src/mcp_server.py<br/>6 tools across both datasets"]
            BOT["Slack Bot<br/>src/slack_bot.py<br/>(university only)"]
        end

        subgraph ENGINE["Shared Query Engine (dataset-aware)"]
            DS["src/datasets.py<br/>registry: endpoint URL,<br/>supported languages, SQL source"]
            TR["src/nl_translator.py<br/>translate(question, dataset)<br/>→ SPARQL [+ SQL]"]
            SE["src/sparql_executor.py<br/>execute(sparql, endpoint)"]
            QE["src/sql_executor.py<br/>execute(sql)<br/>(university only)"]
        end

        subgraph UNI["University data layer (dual SPARQL + SQL)"]
            OTU["Ontop endpoint<br/>localhost:8080"]
            UBD[("university.ddb<br/>(DuckDB file)")]
            UMEM[("In-memory DuckDB<br/>loaded from<br/>data/university.sql")]
            UMAP["ontop/university.obda<br/>+ ontop/university.ttl"]
        end

        subgraph HRBOX["AcmeCorp HR data layer (SPARQL only)"]
            OTH["Ontop endpoint<br/>localhost:8081"]
            HBD[("hr.ddb<br/>(DuckDB file)")]
            HMAP["ontop/hr.obda<br/>+ ontop/hr.ttl"]
            HTTL["hr-dataset/*.ttl<br/>(source of truth)"]
            HSQL["data/hr.sql<br/>(generated)"]
        end

        CLI --> TR
        MCP --> TR
        BOT --> TR
        TR -.consults.- DS

        TR --> SE
        TR --> QE

        SE --> OTU
        SE --> OTH
        QE --> UMEM

        OTU -- JDBC --> UBD
        OTU -.mappings.- UMAP
        OTH -- JDBC --> HBD
        OTH -.mappings.- HMAP

        HTTL -.->|"build_relational.py"| HSQL
        HSQL -.->|"setup.sh"| HBD
    end

    BOT <-->|"WebSocket<br/>(Socket Mode, outbound)"| SS
    CD <-->|"MCP<br/>(local stdio)"| MCP
    TR <-->|"HTTPS<br/>ANTHROPIC_API_KEY"| CA
```

Solid arrows are runtime data flow. Dotted edges are config / build-time
relationships (`build_relational.py` regenerates `data/hr.sql` from the HR Turtle;
`setup.sh` builds the `.ddb` files from the SQL).

---

## Two datasets, one engine

| | University | AcmeCorp HR |
|---|---|---|
| Ontop endpoint | `localhost:8080` | `localhost:8081` |
| DuckDB binary | `university.ddb` | `hr.ddb` |
| Source of truth | `data/university.sql` | `hr-dataset/*.ttl` (9 Turtle files) |
| Languages generated | SPARQL + SQL (parallel) | SPARQL only |
| Display | Side-by-side tables | Single table |
| Slack | Supported | Not exposed |
| MCP tools | `ask_university`, `run_sql`, `get_schema` | `ask_hr`, `run_sparql_hr`, `get_hr_schema` |

The two endpoints are independent processes (`./start_ontop.sh university` and
`./start_ontop.sh hr`) and can run in parallel. DuckDB takes an exclusive lock on
each `.ddb`, which is why `sql_executor.py` loads `data/university.sql` into an
**in-memory** DuckDB rather than opening `university.ddb` directly while Ontop
holds it.

---

## Connection Notes

| Connection | Direction | Protocol | Requires |
|---|---|---|---|
| Slack ↔ Bot | Bot opens outbound WebSocket to Slack | WSS (Socket Mode) | `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` |
| Claude Desktop ↔ MCP server | Local IPC | stdio | Local only |
| HR Web Chat (`web.py`) ↔ MCP server | Local IPC | stdio (persistent `MCPManager`) | Local only |
| Browser ↔ HR Web Chat | Local HTTP | `POST /chat` (NDJSON stream) | `uvicorn web:app` on `:8000` |
| Translator → Claude API | Outbound HTTPS | REST / JSON | `ANTHROPIC_API_KEY` |
| SPARQL executor → Ontop (university) | Local HTTP | HTTP POST | Ontop running on `:8080` |
| SPARQL executor → Ontop (HR) | Local HTTP | HTTP POST | Ontop running on `:8081` |
| Ontop → DuckDB | In-process JDBC | DuckDB JDBC driver | Heap ≥ 2g (`ONTOP_JAVA_ARGS` in `start_ontop.sh`) |
| SQL executor → in-memory DuckDB | In-process | Python library | `data/university.sql` (university only) |

If an Ontop endpoint isn't running, SPARQL queries against that dataset fail
with a helpful error. The university SQL path still works without Ontop (it
goes through the in-memory DuckDB, not the `.ddb` file).

---

## Sequence: question → answer

### University (dual SPARQL + SQL), e.g. via Slack

```
User (Slack)        Slack Servers       slack_bot.py            Engine
     │                   │                   │                     │
     │── "@Bot Q?" ─────►│                   │                     │
     │                   │── WS event ──────►│                     │
     │                   │                   │── translate(Q,      │
     │                   │                   │      "university") ►│── Claude API
     │                   │                   │                     │◄─ SPARQL + SQL
     │                   │                   │── execute() ───────►│── Ontop :8080
     │                   │                   │                     │   + in-mem DuckDB
     │                   │                   │◄── 2× DataFrames ───│
     │                   │◄── post_message ──│                     │
     │◄── reply ─────────│                   │                     │
```

`translate()` runs SPARQL and SQL generation **concurrently** on a
`ThreadPoolExecutor(max_workers=2)`; the executors then run both queries in
parallel as well.

### HR (SPARQL only), e.g. via CLI

```
User (terminal)     nl_query.py          Engine
     │                   │                   │
     │── ./query_hr.sh ──►│                   │
     │                   │── translate(Q,    │
     │                   │      "hr") ──────►│── Claude API
     │                   │                   │◄─ SPARQL
     │                   │── execute() ─────►│── Ontop :8081 → hr.ddb
     │                   │◄── DataFrame ─────│
     │◄── rich table ────│                   │
```

Only one branch runs (no SQL executor, no second thread). The output is a
single results table rather than the university's side-by-side comparison.

---

## HR Web Chat

A claude.ai-style conversational UI for the HR dataset. Unlike the CLI/Slack paths,
it does **not** call the engine directly — it is an MCP *client* that reaches the HR
data only through the MCP server's `ask_hr` / `get_hr_schema` tools. A backend Claude
agent loop orchestrates those tools (with extended thinking, retries, decomposition,
and clarifying questions), and `ask_hr`'s markdown is parsed back into structured rows
so the browser can render tables and charts.

```mermaid
flowchart TB
    subgraph CLOUD["☁️  External APIs"]
        CA["Anthropic Claude API<br/>claude-sonnet-4-6<br/>(thinking + prompt caching)"]
    end

    subgraph BROWSER["🌐  Browser"]
        UI["src/static/index.html<br/>vanilla JS + Chart.js<br/>summary · table · chart · SPARQL"]
    end

    subgraph LAPTOP["💻  Your Laptop"]
        subgraph WEBAPP["FastAPI backend (single worker)"]
            WEB["src/web.py<br/>POST /chat · in-memory SESSIONS"]
            CE["src/chat_engine.py<br/>agent loop · tools=ask_hr,get_hr_schema<br/>retries · decomposition · clarify"]
            MC["src/mcp_client.py<br/>MCPManager (persistent stdio)"]
            HM["src/hr_markdown.py<br/>parse_ask_hr → cols/rows/sparql/error"]
        end

        MCP["src/mcp_server.py<br/>(MCP server, stdio)"]
        OTH["Ontop endpoint<br/>localhost:8081"]
        HBD[("hr.ddb")]
    end

    UI <-->|"POST /chat (NDJSON stream)"| WEB
    WEB --> CE
    CE <-->|"messages + tools"| CA
    CE -->|"call_tool"| MC
    MC <-->|"stdio"| MCP
    CE -.->|"raw ask_hr markdown"| HM
    MCP -->|"ask_hr → translate + execute"| OTH
    OTH -- JDBC --> HBD
    CE <-->|"HTTPS ANTHROPIC_API_KEY"| CA
```

`web.py` keeps one `MCPManager` (one `mcp_server.py` subprocess) alive for the app and
one in-memory conversation per `session_id` — hence the **single-worker** requirement.
Only `ask_hr` / `get_hr_schema` are exposed to the model; the server's other tools are
filtered out in `chat_engine.to_anthropic_tools`.

### Sequence: one chat turn (streamed)

`stream_turn` is an async generator; `POST /chat` forwards each event as one NDJSON
line, so the browser updates **as the turn unfolds** rather than after it finishes.

```
Browser            web.py            chat_engine        MCP server        Ontop :8081
   │                  │                   │                  │                 │
   │─ POST /chat ────►│─ stream_turn() ──►│                  │                 │
   │◄─ session ───────│                   │─ messages.stream (thinking) ─► Claude API
   │◄─ thinking_delta… (reasoning streams live)              │                 │
   │                  │                   │◄─ tool_use × N (ask_hr …)            │
   │◄─ tool_start ────│   (UI: "Querying HR: …")             │                 │
   │                  │                   │─ call_tool(ask_hr) ─►│─ translate+execute ─►│
   │                  │                   │  parse_ask_hr → card │◄── markdown ──│
   │◄─ tool_result ───│   (table/chart card appears now)     │                 │
   │                  │                   │─ messages.stream (tool_result) ► Claude API
   │◄─ text_delta… (summary streams token-by-token)          │                 │
   │◄─ done ──────────│                   │                  │                 │
```

A compound question yields several `ask_hr` `tool_use` blocks (one per sub-question),
each streamed as its own `tool_result` card as it returns; the final `text_delta`
stream synthesizes them. A transient HR-endpoint failure is retried in `chat_engine`
before the error is handed back to the model; an ambiguous question streams a plain
clarifying question with no tool call (`done.needs_clarification = true`).

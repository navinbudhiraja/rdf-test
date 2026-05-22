# Architecture Diagram

## System Overview

```mermaid
flowchart TB
    subgraph SLACK["☁️  Slack Cloud"]
        SU["User in Slack\n(channel / DM)"]
        SS["Slack Servers\n(event routing)"]
        SU <--> SS
    end

    subgraph LAPTOP["💻  Your Laptop (local processes)"]

        subgraph ENTRY["Entry Points"]
            CLI["CLI\nnl_query.py\npython src/nl_query.py \"...\""]
            MCP["MCP Server\nmcp_server.py\n(Claude Desktop)"]
            BOT["Slack Bot\nslack_bot.py\n(NEW)"]
        end

        subgraph ENGINE["Shared Query Engine"]
            TR["nl_translator.py\ntranslate(question)\n→ SPARQL + SQL"]
            SE["sparql_executor.py\nexecute(sparql)\n→ DataFrame"]
            QE["sql_executor.py\nexecute(sql)\n→ DataFrame"]
        end

        subgraph DATA["Data Layer (local)"]
            OT["Ontop VKG\nlocalhost:8080\n(SPARQL endpoint)"]
            DB["DuckDB\n(in-memory)\nloaded from university.sql"]
            SQL["data/university.sql\n+ ontop/university.obda\n+ ontop/university.ttl"]
        end

        CLI --> TR
        MCP --> TR
        BOT --> TR

        TR --> SE
        TR --> QE

        SE --> OT
        QE --> DB
        OT --> SQL
        DB --> SQL
    end

    subgraph CLOUD["☁️  External APIs"]
        CA["Anthropic\nClaude API\nclaude-sonnet-4-6"]
    end

    subgraph DESKTOP["🖥️  Claude Desktop"]
        CD["Claude Desktop\n(MCP client)"]
    end

    %% Slack Socket Mode connection (outbound WebSocket from laptop)
    BOT <-->|"WebSocket\n(Socket Mode)\noutbound only —\nno public URL needed"| SS

    %% Claude Desktop connects to local MCP server
    CD <-->|"MCP protocol\n(local stdio/socket)"| MCP

    %% Claude API calls from translator
    TR <-->|"HTTPS\nANTHROPIC_API_KEY"| CA
```

---

## Connection Notes

| Connection | Direction | Protocol | Requires |
|---|---|---|---|
| Slack ↔ Bot | Bot opens outbound WebSocket to Slack | WSS (WebSocket Secure) | `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN` |
| Bot → Claude API | Outbound HTTPS | REST/JSON | `ANTHROPIC_API_KEY` |
| CLI → Claude API | Outbound HTTPS | REST/JSON | `ANTHROPIC_API_KEY` |
| Claude Desktop → MCP | Local IPC | stdio / local socket | None (local only) |
| Engine → Ontop | Local HTTP | HTTP POST | Ontop running on :8080 |
| Engine → DuckDB | In-process | Python library | `data/university.sql` |

---

## What's New vs. What Exists

```
EXISTING (unchanged)              NEW (additive)
─────────────────────             ───────────────
src/nl_query.py      (CLI)        src/slack_bot.py
src/mcp_server.py    (MCP)        requirements.txt  (+slack_bolt)
src/nl_translator.py              .env               (+2 tokens)
src/sparql_executor.py
src/sql_executor.py
data/university.sql
ontop/university.*
```

The Slack bot is a **thin new entry point** that calls the same engine as the CLI and MCP server. No existing files are modified.

---

## Sequence: Slack Question → Answer

```
User (Slack)          Slack Servers         slack_bot.py           Engine
     │                     │                     │                    │
     │── "@Bot question" ──►│                     │                    │
     │                     │── WebSocket event ──►│                    │
     │                     │                     │── translate() ─────►│── Claude API
     │                     │                     │                    │◄─ SPARQL+SQL
     │                     │                     │── execute() ───────►│── Ontop / DuckDB
     │                     │                     │◄─ DataFrames ───────│
     │                     │◄── post_message() ──│                    │
     │◄── reply in thread ─│                     │                    │
```

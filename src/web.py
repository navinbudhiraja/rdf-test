"""FastAPI backend for the AcmeCorp HR web chat.

Serves a single-page chat UI and a `/chat` endpoint. Each request runs one turn of
the Claude agent loop (`chat_engine.run_turn`) over a persistent MCP session
(`mcp_client.MCPManager`) that exposes only the `ask_hr` / `get_hr_schema` tools.
Conversation state is kept in-memory per `session_id`.

Run (single worker — there is one MCP subprocess and shared in-memory state):

    uvicorn web:app --app-dir src

Requires `ANTHROPIC_API_KEY` (in `.env`) and the HR Ontop endpoint on :8081
(`./start_ontop.sh hr`).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from chat_engine import stream_turn, to_anthropic_tools  # noqa: E402 (after load_dotenv)
from mcp_client import MCPManager  # noqa: E402

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# session_id -> {"messages": [...]}.  In-memory: lost on restart, not shared across
# workers — hence the single-worker requirement.
SESSIONS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set (add it to .env).")
    # Launch the MCP server with the SAME interpreter running the web app so it has
    # the project's dependencies available.
    mcp = MCPManager(python_executable=sys.executable)
    await mcp.start()
    app.state.mcp = mcp
    app.state.tools = to_anthropic_tools(mcp.tools)
    try:
        yield
    finally:
        await mcp.stop()


app = FastAPI(title="AcmeCorp HR Chat", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/chat")
async def chat(req: ChatRequest):
    """Stream a turn as newline-delimited JSON (NDJSON) so the UI updates live:
    a `session` event first, then thinking/tool/text events from `stream_turn`."""
    sid = req.session_id or uuid.uuid4().hex
    session = SESSIONS.setdefault(sid, {"messages": []})
    session["messages"].append({"role": "user", "content": req.message})

    async def events():
        yield json.dumps({"type": "session", "session_id": sid}) + "\n"
        try:
            async for ev in stream_turn(app.state.mcp, session["messages"], app.state.tools):
                yield json.dumps(ev) + "\n"
        except Exception as exc:  # surface backend failures to the client
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=_STATIC), name="static")

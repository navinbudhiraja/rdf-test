"""FastAPI backend for the AcmeCorp HR web chat.

Serves a single-page chat UI and a `/chat` endpoint. Each request runs one turn of
the Claude agent loop (`chat_engine.stream_turn`), which answers HR questions by
calling the pipeline IN-PROCESS (`hr_query`) — no MCP subprocess. Conversation state
is kept in-memory per `session_id`.

Run (single worker — the `SESSIONS` dict is in-memory and not shared across workers):

    uvicorn web:app --app-dir src

Requires `ANTHROPIC_API_KEY` (in `.env`) and the HR Ontop endpoint on :8081
(`./start_ontop.sh hr`).
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from chat_engine import stream_turn  # noqa: E402 (after load_dotenv)

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# session_id -> {"messages": [...]}.  In-memory: lost on restart, not shared across
# workers — hence the single-worker requirement.
SESSIONS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set (add it to .env).")
    yield


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
            async for ev in stream_turn(session["messages"]):
                yield json.dumps(ev) + "\n"
        except Exception as exc:  # surface backend failures to the client
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=_STATIC), name="static")

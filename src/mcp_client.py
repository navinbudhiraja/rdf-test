"""A persistent stdio client to the project's MCP server (`src/mcp_server.py`).

The web backend talks to the HR data only through the MCP tools `ask_hr` and
`get_hr_schema` — it never imports the pipeline directly. Spawning the MCP server
per request would re-import pandas/anthropic/rdflib each time (seconds of cold
start), so `MCPManager` keeps one subprocess + `ClientSession` alive for the whole
app lifetime.

Lifecycle note (important): the `mcp` SDK builds the session from nested async
context managers backed by anyio task groups, which require that each context be
*entered and exited from the same task*. We therefore drive the whole session from
a single long-lived background task (`_run`) and park it on an event until
shutdown — never splitting `__aenter__`/`__aexit__` across FastAPI startup/shutdown
(that triggers anyio's "cancel scope in a different task" error).
"""

from __future__ import annotations

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVER = os.path.join(_HERE, "mcp_server.py")


class MCPManager:
    """Owns the stdio MCP subprocess + ClientSession for the app's lifetime."""

    def __init__(self, python_executable: str | None = None) -> None:
        self._python = python_executable or os.environ.get("PYTHON", "python")
        self.session: ClientSession | None = None
        self.tools: list = []  # cached result of list_tools()
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._error: BaseException | None = None
        self._lock = asyncio.Lock()  # stdio is a single duplex pipe — serialize calls

    async def _run(self) -> None:
        params = StdioServerParameters(
            command=self._python,
            args=[_SERVER],
            env=os.environ.copy(),  # carries ANTHROPIC_API_KEY into the subprocess
        )
        try:
            # Enter AND exit both happen in this task — the anyio-safe pattern.
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    self.tools = (await session.list_tools()).tools
                    self._ready.set()
                    await self._stop.wait()  # park until shutdown
        except BaseException as exc:  # noqa: BLE001 — surface startup failures to start()
            self._error = exc
            self._ready.set()
            raise
        finally:
            self.session = None

    async def start(self) -> None:
        """Spawn the MCP server and wait until the session is initialized."""
        self._task = asyncio.create_task(self._run())
        await self._ready.wait()
        if self._error is not None:
            raise RuntimeError(f"Failed to start MCP server: {self._error}") from self._error

    async def stop(self) -> None:
        """Signal the background task to tear down the session + subprocess."""
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:
                pass  # teardown errors are not actionable on shutdown

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call an MCP tool and return its text content as a single string."""
        if self.session is None:
            raise RuntimeError("MCP session is not running.")
        async with self._lock:
            result = await self.session.call_tool(name, arguments)
        return "".join(
            getattr(block, "text", "")
            for block in result.content
            if getattr(block, "type", None) == "text"
        )

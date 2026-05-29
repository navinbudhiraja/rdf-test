"""The Claude agent loop behind the HR web chat.

A turn is: take the running conversation, let Claude (with extended thinking) decide
when to call the MCP tools `ask_hr` / `get_hr_schema`, run them, feed results back,
and repeat until Claude produces a final natural-language answer. We use the raw
Anthropic Messages API (not the Agent SDK) so we can capture each `ask_hr` call's raw
markdown and parse tables/charts out of it (see `hr_markdown.parse_ask_hr`).

Behaviours the system prompt + loop provide:
- step-by-step planning (extended thinking, optionally surfaced to the UI),
- decomposition: split a compound question into several `ask_hr` calls, then synthesize,
- retries: API-level (AsyncAnthropic max_retries) + tool-level (transient Ontop failures),
- clarifying questions when the request is ambiguous.
"""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

from hr_markdown import parse_ask_hr

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
THINKING_BUDGET = 2048
MAX_ITERATIONS = 10          # decomposition can fan out into several ask_hr calls
TOOL_RETRY_LIMIT = 2         # transient Ontop/MCP failures retried per call
ALLOWED_TOOLS = {"ask_hr", "get_hr_schema"}
_TRANSIENT_HINTS = ("cannot connect", "timed out", "timeout", "connection")

_client = AsyncAnthropic(max_retries=4)  # exponential backoff for 429/5xx/network

HR_SYSTEM = """\
You are an analyst assistant for the **AcmeCorp HR knowledge graph**. You answer \
questions by calling tools — never invent data or guess at figures.

## Domain primer (so your summaries are context-aware)
AcmeCorp is a multinational with three subsidiaries — **AcmeUK, AcmeDE, AcmeUS** — \
each with its own LOCAL job titles. Every local role maps via SKOS to a single GLOBAL \
role catalog, which is anchored to ESCO/ISCO occupations. Roles have a job family and \
a seniority level (L1–L9). People hold posts (org:Post) via memberships; posts report \
to other posts. Some role mappings are low-confidence or unapproved and "need review".

## Tools
- `get_hr_schema()` — returns the ontology reference (prefixes, classes, relationships). \
Call it when you are unsure of the vocabulary needed to phrase a question.
- `ask_hr(question)` — answers ONE natural-language HR question: it generates SPARQL, \
runs it against the HR graph, and returns markdown containing the query and a results \
table. Ask focused, single-intent questions.

## How to work
- Plan before querying. For a compound question, DECOMPOSE it into focused \
sub-questions and make a SEPARATE `ask_hr` call for each, then combine the results into \
one answer.
- Try hard. If a call errors or returns no rows, diagnose and retry with a reformulated \
question (consult `get_hr_schema`, relax a filter, try alternate terminology) before \
giving up.
- If the request is genuinely AMBIGUOUS and a wrong guess would mislead, ask ONE concise \
clarifying question instead of calling a tool. Don't over-ask when a reasonable default \
exists — just state the assumption and proceed.

## Writing the answer
After the tool results come back, write a tight natural-language summary that \
INTERPRETS the data — lead with the direct answer, then call out the largest/smallest, \
notable comparisons or outliers, and totals. Relate it to what the user asked and to \
earlier turns in the conversation. Use the domain context (subsidiaries, seniority, \
role/ESCO mappings) to make it meaningful. If results are unavailable (e.g. the HR \
database is unreachable), say so plainly.

IMPORTANT: write PROSE ONLY. Never reproduce the results as a markdown table or \
pipe-delimited rows — the UI renders the table and chart separately below your reply, \
so a table in your text would be a confusing duplicate. Refer to figures inline (e.g. \
"AcmeUS leads with 14") rather than listing them in a table.\
"""


def to_anthropic_tools(mcp_tools) -> list[dict]:
    """Convert MCP tool definitions to Anthropic tool schema, filtered to the two
    HR tools so the model can never reach the server's other tools."""
    tools = [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
        if t.name in ALLOWED_TOOLS
    ]
    tools.sort(key=lambda t: t["name"])  # stable order for prompt caching
    return tools


def _is_transient(error: str | None) -> bool:
    return bool(error) and any(h in error.lower() for h in _TRANSIENT_HINTS)


async def _call_tool_with_retry(mcp, name: str, arguments: dict) -> tuple[str, dict | None]:
    """Call an MCP tool, returning (raw_markdown, parsed-or-None).

    `parsed` is only produced for `ask_hr`. Transient HR-endpoint failures are retried
    a few times with backoff before the (error) result is handed back to the model.
    """
    last_raw = ""
    for attempt in range(TOOL_RETRY_LIMIT + 1):
        try:
            raw = await mcp.call_tool(name, arguments)
        except Exception as exc:  # subprocess died / protocol error
            return (f"> Unavailable: {exc}", parse_ask_hr(f"## SPARQL Results\n\n> Unavailable: {exc}\n"))
        last_raw = raw
        if name != "ask_hr":
            return raw, None
        parsed = parse_ask_hr(raw)
        if not _is_transient(parsed.get("error")) or attempt == TOOL_RETRY_LIMIT:
            return raw, parsed
        await asyncio.sleep(0.5 * (attempt + 1))  # brief backoff, then retry
    return last_raw, parse_ask_hr(last_raw)


async def stream_turn(mcp, messages: list[dict], tools: list[dict]):
    """Run one user turn, yielding progress events as they happen so the UI can
    update live instead of waiting for the whole turn. Mutates `messages` (assistant
    + tool_result turns are appended so history persists across turns).

    Event shapes (all JSON-serializable dicts):
      {"type":"thinking_delta","text":...}   incremental extended-thinking text
      {"type":"tool_start","tool":...,"question":...}   an ask_hr/get_hr_schema call began
      {"type":"tool_result","card":{...}}    a parsed ask_hr result (table/chart payload)
      {"type":"text_delta","text":...}       incremental final-answer text
      {"type":"done","needs_clarification":bool}
    """
    emitted_cards = 0
    text_acc = ""

    for _ in range(MAX_ITERATIONS):
        async with _client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
            system=[{"type": "text", "text": HR_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type != "content_block_delta":
                    continue
                dt = getattr(event.delta, "type", None)
                if dt == "thinking_delta":
                    yield {"type": "thinking_delta", "text": event.delta.thinking}
                elif dt == "text_delta":
                    text_acc += event.delta.text
                    yield {"type": "text_delta", "text": event.delta.text}
            final = await stream.get_final_message()

        # Preserve the assistant turn verbatim — thinking blocks (with signatures)
        # and tool_use blocks must be passed back on subsequent calls.
        messages.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            break

        tool_result_blocks = []
        for block in final.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            args = dict(block.input or {})
            yield {
                "type": "tool_start",
                "tool": block.name,
                "question": args.get("question") if block.name == "ask_hr" else None,
            }
            raw, parsed = await _call_tool_with_retry(mcp, block.name, args)
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": raw,
                "is_error": bool(parsed and parsed.get("error")),
            })
            if block.name == "ask_hr" and parsed is not None:
                emitted_cards += 1
                yield {"type": "tool_result", "card": {
                    "tool": "ask_hr",
                    "sparql": parsed["sparql"],
                    "columns": parsed["columns"],
                    "rows": parsed["rows"],
                    "rowCount": parsed["rowCount"],
                    "error": parsed["error"],
                }}

        messages.append({"role": "user", "content": tool_result_blocks})
    else:
        # Loop exhausted without a final answer — emit a fallback.
        if not text_acc:
            text_acc = "I wasn't able to finish answering — please try rephrasing."
            yield {"type": "text_delta", "text": text_acc}

    yield {
        "type": "done",
        "needs_clarification": emitted_cards == 0 and text_acc.rstrip().endswith("?"),
    }


async def run_turn(mcp, messages: list[dict], tools: list[dict]) -> dict:
    """Non-streaming convenience wrapper around `stream_turn` — collects the events
    into a single result dict (used by tests / any non-streaming caller)."""
    text, thinking, cards, needs = "", "", [], False
    async for ev in stream_turn(mcp, messages, tools):
        t = ev["type"]
        if t == "text_delta":
            text += ev["text"]
        elif t == "thinking_delta":
            thinking += ev["text"]
        elif t == "tool_result":
            cards.append(ev["card"])
        elif t == "done":
            needs = ev["needs_clarification"]
    return {
        "text": text.strip(),
        "thinking": thinking.strip() or None,
        "tool_results": cards,
        "needs_clarification": needs,
    }

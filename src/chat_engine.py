"""The Claude agent loop behind the HR web chat.

A turn is: take the running conversation, let Claude (with extended thinking) decide
when to call the HR tools `ask_hr` / `get_hr_schema`, run them IN-PROCESS (via
`hr_query`), feed results back, and repeat until Claude produces a final
natural-language answer. We use the raw Anthropic Messages API (not the Agent SDK)
so we can stream thinking/text and capture each `ask_hr` call's structured result
(table/chart payload) for the UI.

`ask_hr` returns structured data directly (`hr_query.run`) — no MCP subprocess and no
markdown round-trip. (`mcp_server.py` is still the MCP surface for Claude Desktop;
the web app just calls the same pipeline in-process.)

Behaviours the system prompt + loop provide:
- step-by-step planning (extended thinking, optionally surfaced to the UI),
- decomposition: split a compound question into several `ask_hr` calls, then synthesize,
- retries: API-level (AsyncAnthropic max_retries) + tool-level (transient Ontop failures),
- clarifying questions when the request is ambiguous.
"""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

import hr_query

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
THINKING_BUDGET = 2048
MAX_ITERATIONS = 10          # decomposition can fan out into several ask_hr calls
TOOL_RETRY_LIMIT = 2         # transient Ontop failures retried per call
_TRANSIENT_HINTS = ("cannot connect", "timed out", "timeout", "connection")

_client = AsyncAnthropic(max_retries=4)  # exponential backoff for 429/5xx/network

# Hand-written tool schemas (sorted by name for stable prompt caching). The web app
# exposes exactly these two HR tools — they map to `hr_query` functions, not MCP.
HR_TOOLS = [
    {
        "name": "ask_hr",
        "description": (
            "Answer ONE focused natural-language question about the AcmeCorp HR "
            "dataset. Generates SPARQL, runs it against the HR knowledge graph, and "
            "returns the query plus a results table. Ask single-intent questions; "
            "decompose compound questions into separate calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "get_hr_schema",
        "description": (
            "Return the AcmeCorp HR ontology reference — prefixes, classes, "
            "properties, and IRI patterns. Call it when unsure of the vocabulary "
            "needed to phrase a question."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

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
runs it against the HR graph, and returns the query and a results table. Ask focused, \
single-intent questions.

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


def _is_transient(error: str | None) -> bool:
    return bool(error) and any(h in error.lower() for h in _TRANSIENT_HINTS)


def _card_to_text(card: dict) -> str:
    """Render an ask_hr result as compact markdown for the MODEL to read (one-way —
    the UI uses the structured card directly, so this is never parsed back)."""
    if card["error"]:
        return f"> Error: {card['error']}"
    columns, rows = card["columns"], card["rows"]
    if not rows:
        return "_No rows returned._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(r.get(c, "")) for c in columns) + " |"
        for r in rows
    ]
    n = card["rowCount"]
    return "\n".join([header, sep, *body]) + f"\n\n_{n} row{'s' if n != 1 else ''}_"


async def _ask_hr_with_retry(question: str) -> dict:
    """Run `ask_hr` in-process, retrying a few times with backoff on transient HR
    endpoint failures before handing the (error) card back to the model."""
    for attempt in range(TOOL_RETRY_LIMIT + 1):
        card = await asyncio.to_thread(hr_query.run, question)  # blocking pipeline off the loop
        if not _is_transient(card.get("error")) or attempt == TOOL_RETRY_LIMIT:
            return card
        await asyncio.sleep(0.5 * (attempt + 1))  # brief backoff, then retry
    return card


async def stream_turn(messages: list[dict]):
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
            tools=HR_TOOLS,
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
            is_ask = block.name == "ask_hr"
            yield {
                "type": "tool_start",
                "tool": block.name,
                "question": args.get("question") if is_ask else None,
            }

            if is_ask:
                card = await _ask_hr_with_retry(args.get("question", ""))
                result_text = _card_to_text(card)
                is_error = bool(card["error"])
                emitted_cards += 1
                yield {"type": "tool_result", "card": {"tool": "ask_hr", **card}}
            elif block.name == "get_hr_schema":
                result_text, is_error = hr_query.SCHEMA, False
            else:  # the model can only see HR_TOOLS, so this is defensive
                result_text, is_error = f"Unknown tool: {block.name}", True

            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
                "is_error": is_error,
            })

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


async def run_turn(messages: list[dict]) -> dict:
    """Non-streaming convenience wrapper around `stream_turn` — collects the events
    into a single result dict (used by tests / any non-streaming caller)."""
    text, thinking, cards, needs = "", "", [], False
    async for ev in stream_turn(messages):
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

"""Parse the markdown that the MCP `ask_hr` tool returns into structured data.

`ask_hr` (see `mcp_server.py::_answer` / `_df_to_markdown`) emits a deterministic,
section-anchored markdown string for the SPARQL-only HR dataset:

    ## Question · AcmeCorp HR

    <question>

    ## Generated SPARQL

    ```sparql
    <query>
    ```

    ## SPARQL Results

    | col | col |
    | --- | --- |
    | v   | v   |

    _N rows_

The Results section has three real shapes: a GitHub pipe table, the empty marker
`_No rows returned._`, or an error line `> Unavailable: <msg>` (Ontop down). On a
translation failure the whole string is instead `**Translation error:** <msg>` with
no sections at all. This module turns any of those into one structured dict so the
web layer can render tables/charts — the markdown is the only data channel available
(we are restricted to the `ask_hr` / `get_hr_schema` tools and cannot import the
pipeline directly).
"""

from __future__ import annotations

import re

_SPARQL_RE = re.compile(r"```sparql\s*\n(.*?)```", re.DOTALL)
_ROWS_FOOTER_RE = re.compile(r"_(\d+)\s+rows?_")


def extract_sparql(md: str) -> str | None:
    """Return the first fenced ```sparql block, or None if absent."""
    m = _SPARQL_RE.search(md)
    return m.group(1).strip() if m else None


def _slice_section(md: str, header: str) -> str | None:
    """Return the body of the `## <header>` section (up to the next `## ` or EOF)."""
    m = re.search(
        rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
        md,
        re.DOTALL | re.MULTILINE,
    )
    return m.group(1).strip() if m else None


def _split_row(line: str) -> list[str]:
    """Split a GitHub pipe-table row into trimmed cell values."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _parse_pipe_table(section: str) -> tuple[list[str], list[dict]]:
    """Parse a GitHub pipe table into (columns, rows-as-dicts)."""
    table_lines = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []
    columns = _split_row(table_lines[0])
    rows: list[dict] = []
    for line in table_lines[2:]:  # skip header row + |---|---| separator
        values = _split_row(line)
        if len(values) == len(columns):
            rows.append(dict(zip(columns, values)))
    return columns, rows


def parse_ask_hr(md: str) -> dict:
    """Parse an `ask_hr` markdown response into a structured result.

    Returns a dict with:
      sparql      — the generated SPARQL query (str | None)
      columns     — list[str] of result column names ([] on error/empty)
      rows        — list[dict] (one per result row; [] on error/empty)
      rowCount    — len(rows)
      error       — human-readable error message (str | None)
      rawMarkdown — the original markdown, kept as a rendering fallback
    """
    sparql = extract_sparql(md)
    results = _slice_section(md, "SPARQL Results")

    error: str | None = None
    columns: list[str] = []
    rows: list[dict] = []

    if results is None:
        # No Results section at all — e.g. "**Translation error:** ..." or an
        # otherwise malformed response. Surface the whole thing as an error.
        error = md.strip() or "No results returned."
    else:
        first_line = results.split("\n", 1)[0].strip()
        if results.startswith(">") or first_line.startswith("> Unavailable") or "Unavailable:" in first_line:
            # Error branch: "> Unavailable: <msg>" (+ optional Tip line).
            error = re.sub(r"^>\s*(\*\*Tip:\*\*)?\s*", "", first_line).strip()
            error = error.replace("Unavailable:", "").strip() or first_line.lstrip("> ").strip()
        elif results.startswith("_No rows"):
            # Empty result set — not an error, just zero rows.
            columns, rows = [], []
        else:
            columns, rows = _parse_pipe_table(results)

    # Cross-check against the "_N rows_" footer the server emits; a mismatch hints
    # at a parsing problem (e.g. a literal '|' inside a cell) without failing hard.
    footer_count: int | None = None
    if results:
        fm = _ROWS_FOOTER_RE.search(results)
        if fm:
            footer_count = int(fm.group(1))

    parsed_warning = (
        footer_count is not None and not error and footer_count != len(rows)
    )

    return {
        "sparql": sparql,
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "error": error,
        "rawMarkdown": md,
        "footerRowCount": footer_count,
        "parseMismatch": parsed_warning,
    }

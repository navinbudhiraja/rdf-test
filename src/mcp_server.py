import sys
import os

# Must happen before local imports so ANTHROPIC_API_KEY is set when nl_translator initializes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

import concurrent.futures
import pandas as pd
from mcp.server.fastmcp import FastMCP

import nl_translator
import sparql_executor
import sql_executor

mcp = FastMCP("university-query")


def _df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows returned._"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "| " + " | ".join("---" for _ in cols) + " |"
    rows   = [
        "| " + " | ".join(str(v) if v is not None else "" for v in row) + " |"
        for row in df.itertuples(index=False, name=None)
    ]
    return "\n".join([header, sep] + rows)


@mcp.tool()
def ask_university(question: str) -> str:
    """
    Answer a natural language question about the university dataset.

    Translates the question into SPARQL and SQL using Claude, executes both,
    and returns formatted markdown with the generated queries and results.
    SPARQL requires Ontop running (./start_ontop.sh); SQL always works.

    Examples: "List all students", "Which professors teach more than one course?",
    "Who is enrolled in Database Systems?"
    """
    try:
        sparql, sql = nl_translator.translate(question)
    except RuntimeError as exc:
        return f"**Translation error:** {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        sf = pool.submit(sparql_executor.execute, sparql)
        qf = pool.submit(sql_executor.execute, sql)
        try:
            sparql_df, sparql_err = sf.result(), None
        except RuntimeError as exc:
            sparql_df, sparql_err = None, str(exc)
        try:
            sql_df, sql_err = qf.result(), None
        except RuntimeError as exc:
            sql_df, sql_err = None, str(exc)

    parts = [
        f"## Question\n\n{question}\n",
        f"## Generated SPARQL\n\n```sparql\n{sparql}\n```\n",
        f"## Generated SQL\n\n```sql\n{sql}\n```\n",
    ]

    if sparql_err:
        tip = "\n\n> **Tip:** Start Ontop with `./start_ontop.sh` to enable SPARQL results." \
              if "Cannot connect" in sparql_err else ""
        parts.append(f"## SPARQL Results\n\n> Unavailable: {sparql_err.splitlines()[0]}{tip}\n")
    else:
        parts.append(f"## SPARQL Results\n\n{_df_to_markdown(sparql_df)}\n")

    if sql_err:
        parts.append(f"## SQL Results\n\n> Error: {sql_err}\n")
    else:
        n = len(sql_df)
        parts.append(f"## SQL Results\n\n{_df_to_markdown(sql_df)}\n\n_{n} row{'s' if n != 1 else ''}_\n")

    return "\n".join(parts)


@mcp.tool()
def run_sql(query: str) -> str:
    """
    Execute a raw SQL SELECT query against the university DuckDB database.

    Call get_schema() first if you need to know table and column names.
    Example: "SELECT * FROM academic WHERE position = 1"
    """
    try:
        df = sql_executor.execute(query)
    except RuntimeError as exc:
        return f"**SQL error:**\n\n```\n{exc}\n```"
    n = len(df)
    return f"{_df_to_markdown(df)}\n\n_{n} row{'s' if n != 1 else ''}_"


@mcp.tool()
def get_schema() -> str:
    """
    Return the university database schema — tables, columns, types, and position
    code legend — so you can write accurate SQL or ask well-formed questions.
    """
    return """\
## University Database Schema

**student** — s_id INT (PK), fname VARCHAR, lname VARCHAR
**academic** — a_id INT (PK), fname VARCHAR, lname VARCHAR, position INT
  position codes: 1 = Full Professor, 2 = Associate Professor, 3 = Assistant Professor, 9 = PostDoc
**course** — c_id INT (PK), title VARCHAR
**teaching** — a_id INT (FK → academic), c_id INT (FK → course)
**course_registration** — s_id INT (FK → student), c_id INT (FK → course)

Data: 10 students · 6 academics · 5 courses
Courses: Information Systems, Software Engineering, Database Systems, Artificial Intelligence, Computer Networks
"""


if __name__ == "__main__":
    mcp.run()

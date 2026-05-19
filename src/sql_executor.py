"""Execute SQL queries against the university database and return a DataFrame.

Uses an in-memory DuckDB connection populated from university.sql so there is
no file-lock conflict with the Ontop JDBC process holding university.ddb.
"""

import os
import duckdb
import pandas as pd

SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "university.sql")


def _make_connection() -> duckdb.DuckDBPyConnection:
    sql_path = os.path.abspath(SQL_PATH)
    if not os.path.exists(sql_path):
        raise RuntimeError(
            f"Schema file not found: {sql_path}\n"
            "Run ./setup.sh first."
        )
    con = duckdb.connect()  # in-memory; no file lock
    with open(sql_path) as f:
        raw = f.read()
    for stmt in raw.split(";"):
        stmt = stmt.strip()
        code_lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
        if code_lines:
            con.execute(stmt)
    return con


def execute(sql: str) -> pd.DataFrame:
    """
    Run a SQL SELECT query against an in-memory DuckDB loaded from university.sql.
    Returns a pandas DataFrame.
    Raises RuntimeError with a clear message on failure.
    """
    try:
        con = _make_connection()
        df = con.execute(sql).df()
        con.close()
    except duckdb.Error as exc:
        raise RuntimeError(f"SQL execution error:\n{exc}") from exc

    return df

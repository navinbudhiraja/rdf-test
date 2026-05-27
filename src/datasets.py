"""Registry of queryable datasets and how to reach each one.

Used by the CLI and MCP server to route a question to the right Claude prompts,
SPARQL endpoint, and (for SQL-capable datasets) relational source.

- university: dual SPARQL + SQL, Ontop on :8080, in-memory DuckDB from university.sql
- hr:         SPARQL-only, Ontop on :8081 over the relational HR tables (hr.ddb)
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.abspath(os.path.join(_HERE, "..", "data"))

DATASETS = {
    "university": {
        "label": "University",
        "languages": ["sparql", "sql"],
        "sparql_endpoint": "http://localhost:8080/sparql",
        "sql_path": os.path.join(_DATA, "university.sql"),
    },
    "hr": {
        "label": "AcmeCorp HR",
        "languages": ["sparql"],
        "sparql_endpoint": "http://localhost:8081/sparql",
        "sql_path": None,
    },
}

DEFAULT_DATASET = "university"


def get(dataset: str) -> dict:
    if dataset not in DATASETS:
        raise ValueError(
            f"Unknown dataset '{dataset}'. Choices: {', '.join(DATASETS)}"
        )
    return DATASETS[dataset]

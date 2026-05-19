"""Execute SPARQL queries against the Ontop endpoint and return a DataFrame."""

import requests
import pandas as pd

ENDPOINT = "http://localhost:8080/sparql"
TIMEOUT = 30


def execute(sparql: str) -> pd.DataFrame:
    """
    POST a SPARQL SELECT query to the Ontop endpoint.
    Returns a pandas DataFrame with one column per SELECT variable.
    Raises RuntimeError with a clear message on failure.
    """
    try:
        resp = requests.post(
            ENDPOINT,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ontop SPARQL endpoint at {ENDPOINT}.\n"
            "Start it with:\n\n"
            "  ./ontop-cli/ontop endpoint \\\n"
            "      -m ontop/university.obda \\\n"
            "      -t ontop/university.ttl \\\n"
            "      -p ontop/database.properties"
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"SPARQL endpoint returned HTTP {resp.status_code}:\n{resp.text[:500]}"
        )

    data = resp.json()
    columns: list[str] = data["head"]["vars"]
    rows = [
        {col: binding[col]["value"] if col in binding else None for col in columns}
        for binding in data["results"]["bindings"]
    ]
    return pd.DataFrame(rows, columns=columns)

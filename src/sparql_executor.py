"""Execute SPARQL queries against the Ontop endpoint and return a DataFrame."""

import requests
import pandas as pd

ENDPOINT = "http://localhost:8080/sparql"
TIMEOUT = 30


def execute(sparql: str, endpoint: str = ENDPOINT) -> pd.DataFrame:
    """
    POST a SPARQL SELECT query to an Ontop endpoint.
    Returns a pandas DataFrame with one column per SELECT variable.
    Raises RuntimeError with a clear message on failure.
    """
    try:
        resp = requests.post(
            endpoint,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ontop SPARQL endpoint at {endpoint}.\n"
            "Start it with:  ./start_ontop.sh           (university, port 8080)\n"
            "            or:  ./start_ontop.sh hr        (HR, port 8081)"
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

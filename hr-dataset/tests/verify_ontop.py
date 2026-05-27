#!/usr/bin/env python3
"""Round-trip verification for the HR dataset's relational + Ontop layer.

Data-driven: discovers every *.rq in hr-dataset/queries/ and, for each query,
runs it against
  (a) the rdflib ORACLE — the original Turtle loaded in memory, and
  (b) the HR Ontop endpoint (relational tables + ontop/hr.obda),
then asserts the two result sets are equal (order-independent, with numeric /
datetime canonicalization). Exits non-zero on any mismatch.

Adding a new test later = drop a new NN_name.rq into hr-dataset/queries/. It is
picked up automatically; the oracle computes its expected answer from the Turtle.

USAGE
-----
    pip install rdflib requests
    ./start_ontop.sh hr            # in another terminal (endpoint on :8081)
    python hr-dataset/tests/verify_ontop.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
HR_DIR = HERE.parent
QUERY_DIR = HR_DIR / "queries"
ENDPOINT = "http://localhost:8081/sparql"

sys.path.insert(0, str(HR_DIR))
from build_relational import load_graph  # oracle loader (merges split literals)

_NUMERIC = re.compile(r"-?\d+(\.\d+)?$")


def canon(value):
    """Canonicalize a result value so the two engines compare equal."""
    if value is None:
        return None
    s = str(value)
    if _NUMERIC.match(s):
        return ("num", float(s))
    if "T" in s and re.match(r"\d{4}-\d{2}-\d{2}T", s):
        try:
            return ("dt", datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat())
        except ValueError:
            pass
    return s


def row_key(varname_value_pairs) -> frozenset:
    return frozenset((v, canon(val)) for v, val in varname_value_pairs)


def oracle_rows(graph, query_text: str) -> Counter:
    res = graph.query(query_text)
    rows = []
    for row in res:
        rows.append(row_key((str(v), row[v]) for v in res.vars))
    return Counter(rows)


def ontop_rows(query_text: str) -> Counter:
    resp = requests.post(
        ENDPOINT,
        data={"query": query_text},
        headers={"Accept": "application/sparql-results+json"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = []
    for b in data["results"]["bindings"]:
        rows.append(row_key((v, b[v]["value"] if v in b else None) for v in data["head"]["vars"]))
    return Counter(rows)


def main() -> int:
    try:
        requests.get(ENDPOINT, timeout=5)
    except requests.exceptions.RequestException:
        print(f"ERROR: HR Ontop endpoint not reachable at {ENDPOINT}.\n"
              f"Start it first:  ./start_ontop.sh hr", file=sys.stderr)
        return 2

    print("Loading rdflib oracle (original Turtle)...")
    graph = load_graph()
    print(f"  oracle graph: {len(graph)} triples\n")

    query_files = sorted(QUERY_DIR.glob("*.rq"))
    if not query_files:
        print(f"No .rq files found in {QUERY_DIR}", file=sys.stderr)
        return 2

    failures = 0
    for qf in query_files:
        qtext = qf.read_text(encoding="utf-8")
        try:
            expected = oracle_rows(graph, qtext)
            actual = ontop_rows(qtext)
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] {qf.name}: {exc}")
            failures += 1
            continue

        if expected == actual:
            print(f"  [PASS] {qf.name:36} {sum(expected.values())} rows match")
        else:
            failures += 1
            missing = expected - actual   # in oracle, not in Ontop
            extra = actual - expected     # in Ontop, not in oracle
            print(f"  [FAIL] {qf.name:36} oracle={sum(expected.values())} ontop={sum(actual.values())}")
            for label, diff in (("only in ORACLE", missing), ("only in ONTOP", extra)):
                for rowkey in list(diff)[:8]:
                    print(f"           {label}: {dict(rowkey)}")

    print()
    print("=" * 70)
    if failures == 0:
        print(f"RESULT: all {len(query_files)} queries match the oracle")
    else:
        print(f"RESULT: {failures} of {len(query_files)} queries FAILED")
    print("=" * 70)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

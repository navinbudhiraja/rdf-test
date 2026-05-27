#!/usr/bin/env python3
"""
End-to-end test harness for the AcmeCorp HR ontology dataset.

Loads all TTL files in order, parses every .rq query in queries/, runs them,
and prints a pass/fail summary against the expected counts and contents
documented in tests/expected_results.md.

Optionally runs SHACL validation if pyshacl is installed.

USAGE
-----
    pip install rdflib pyshacl
    python tests/load_and_query.py

The script discovers files relative to its own location, so it works from
any cwd.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from rdflib import Graph, Namespace
except ImportError:
    print("ERROR: rdflib is not installed. Run:  pip install rdflib pyshacl", file=sys.stderr)
    sys.exit(1)

try:
    from pyshacl import validate as shacl_validate
    HAVE_PYSHACL = True
except ImportError:
    HAVE_PYSHACL = False


ROOT = Path(__file__).resolve().parent.parent
QUERY_DIR = ROOT / "queries"

DATA_FILES = [
    "01_ontology.ttl",
    "02_global_reference.ttl",
    "03_local_acme_uk.ttl",
    "04_local_acme_de.ttl",
    "05_local_acme_us.ttl",
    "06_mappings.ttl",
    "07_esco_anchors.ttl",
    "08_instance_data.ttl",
]
SHAPES_FILE = "09_shapes.shacl.ttl"


# ---- expected results (rows where order is unimportant) -------------------

EXPECTED = {
    "01_global_role_to_employees.rq": {
        "expected_count": 3,
        "must_contain_names": {"Alice Chen", "Olga Weber", "Brianna Lee"},
    },
    "02_cross_subsidiary_equivalents.rq": {
        "expected_count": 2,
        "must_contain_substrings": {"Softwareentwickler III", "Software Engineer III"},
    },
    "03_skill_to_people_via_esco.rq": {
        "expected_count": 9,
        "must_contain_names": {
            "Alice Chen", "Bob Singh", "Carol O'Brien",
            "Noah Becker", "Olga Weber", "Peter Müller",
            "Aiden Garcia", "Brianna Lee", "Carlos Rivera",
        },
    },
    "04_reporting_lines.rq": {
        "expected_count": 3,
        "must_contain_substrings": {
            "Senior SWE, London Payments",
            "Engineering Manager, London Payments",
            "Head of Engineering, UK",
        },
    },
    "05_open_postings_by_role.rq": {
        "expected_count": 1,
        "must_contain_substrings": {"Engineering Manager, SF Payments"},
    },
    "06_mappings_needing_review.rq": {
        "expected_count": 2,
        "must_contain_substrings": {"Customer Success Associate", "Area VP of Sales"},
    },
    "07_unmapped_local_roles.rq": {
        "expected_count": 1,
        "must_contain_substrings": {"Kundenservicemitarbeiter"},
    },
}


# ---- helpers --------------------------------------------------------------

def hr(char: str = "-", n: int = 78) -> str:
    return char * n


def load_graph() -> Graph:
    g = Graph()
    print(hr("="))
    print("LOADING DATA")
    print(hr("="))
    for fname in DATA_FILES:
        path = ROOT / fname
        if not path.exists():
            raise FileNotFoundError(f"Missing data file: {path}")
        before = len(g)
        g.parse(path, format="turtle")
        after = len(g)
        print(f"  {fname:32}  +{after - before:>5} triples  (total: {after})")
    print()
    return g


def run_query_tests(g: Graph) -> int:
    print(hr("="))
    print("RUNNING QUERIES")
    print(hr("="))
    failures = 0

    for qfile_name in sorted(EXPECTED.keys()):
        qpath = QUERY_DIR / qfile_name
        if not qpath.exists():
            print(f"  [FAIL] {qfile_name}: file not found at {qpath}")
            failures += 1
            continue

        query_text = qpath.read_text(encoding="utf-8")
        try:
            results = list(g.query(query_text))
        except Exception as exc:
            print(f"  [FAIL] {qfile_name}: query execution error: {exc}")
            failures += 1
            continue

        exp = EXPECTED[qfile_name]
        n_rows = len(results)

        # check count
        count_ok = n_rows == exp["expected_count"]

        # check required content
        flat_strs = []
        for row in results:
            for term in row:
                flat_strs.append(str(term) if term is not None else "")
        flat = " ".join(flat_strs)

        content_ok = True
        if "must_contain_names" in exp:
            for name in exp["must_contain_names"]:
                if name not in flat:
                    content_ok = False
                    break
        if content_ok and "must_contain_substrings" in exp:
            for ss in exp["must_contain_substrings"]:
                if ss not in flat:
                    content_ok = False
                    break

        status = "PASS" if (count_ok and content_ok) else "FAIL"
        marker = " " if status == "PASS" else "*"
        print(f"  [{status}]{marker} {qfile_name}")
        print(f"          got {n_rows} rows, expected {exp['expected_count']}")
        if not count_ok or not content_ok:
            failures += 1
            print(f"          --- diagnostic dump of result rows ---")
            for r in results:
                print(f"            {tuple(str(x) for x in r)}")
            print(f"          --- end dump ---")
    print()
    return failures


def run_shacl(g: Graph) -> int:
    print(hr("="))
    print("RUNNING SHACL VALIDATION")
    print(hr("="))
    if not HAVE_PYSHACL:
        print("  pyshacl is not installed; skipping. To enable: pip install pyshacl\n")
        return 0

    shapes_path = ROOT / SHAPES_FILE
    if not shapes_path.exists():
        print(f"  shapes file missing: {shapes_path}")
        return 1

    shapes_g = Graph().parse(shapes_path, format="turtle")
    conforms, report_g, report_text = shacl_validate(
        data_graph=g,
        shacl_graph=shapes_g,
        inference="none",
        abort_on_first=False,
        meta_shacl=False,
        debug=False,
    )

    # We deliberately expect ONE violation: the unmapped DE role.
    expected_violation_marker = "KundenServiceMitarbeiter"
    if conforms:
        print("  [FAIL] SHACL reported zero violations, but we expected one")
        print(f"         on {expected_violation_marker} (unmapped local role).")
        return 1

    if expected_violation_marker in report_text:
        # count how many distinct violations were reported; expect exactly 1
        n_violations = report_text.count("Constraint Violation in")
        if n_violations == 1:
            print(f"  [PASS]  exactly 1 SHACL violation, on {expected_violation_marker}")
            print()
            return 0
        else:
            print(f"  [FAIL]  expected 1 violation but got {n_violations}")
            print(hr("."))
            print(report_text)
            print(hr("."))
            return 1
    else:
        print("  [FAIL] SHACL reported violations, but not the expected one.")
        print(hr("."))
        print(report_text)
        print(hr("."))
        return 1


def main() -> int:
    try:
        g = load_graph()
    except Exception as exc:
        print(f"FATAL: failed to load graph: {exc}", file=sys.stderr)
        return 2

    print(f"  graph total: {len(g)} triples")
    print()

    failures = run_query_tests(g)
    failures += run_shacl(g)

    print(hr("="))
    if failures == 0:
        print("RESULT: all checks passed")
    else:
        print(f"RESULT: {failures} check(s) failed")
    print(hr("="))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

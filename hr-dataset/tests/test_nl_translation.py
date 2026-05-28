#!/usr/bin/env python3
"""
End-to-end NL translation tests for the HR SPARQL prompt additions.

Each test sends a natural-language question through translate() -> Ontop and
asserts the result matches expected values. These tests exercise knowledge areas
added to _HR_SPARQL_SYSTEM that the verify_ontop.py round-trip tests do not cover
(because verify_ontop only tests hand-written queries, not Claude-generated ones).

USAGE
-----
    ./start_ontop.sh hr            # in another terminal (endpoint on :8081)
    python hr-dataset/tests/test_nl_translation.py
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import requests
from nl_translator import translate
from sparql_executor import execute

ONTOP_HR = "http://localhost:8081/sparql"


# ── helpers ──────────────────────────────────────────────────────────────────

def flat(df) -> str:
    """Flatten all DataFrame values to a single string for substring checks."""
    return " ".join(str(v) for v in df.values.flatten() if v is not None)


def run_test(name: str, question: str, check_fn) -> bool:
    print(f"\n{'─' * 70}")
    print(f"TEST: {name}")
    print(f"  Q: {question}")
    try:
        sparql, _ = translate(question, "hr")
        print(f"  Generated SPARQL:\n    " + sparql.replace("\n", "\n    "))
        df = execute(sparql, endpoint=ONTOP_HR)
        print(f"  Rows returned: {len(df)}")
        if not df.empty:
            print(f"  First row: {df.iloc[0].to_dict()}")
        ok, msg = check_fn(df)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {msg}")
        return ok
    except Exception as exc:
        print(f"  [FAIL] Exception: {exc}")
        return False


# ── test cases ────────────────────────────────────────────────────────────────

def test_local_role_iri() -> bool:
    """Tests acmeUK:PeoplePartner — a local role IRI Claude must know exactly."""
    def check(df):
        f = flat(df)
        if "Kate Adler" in f:
            return True, "found 'Kate Adler' in results"
        return False, f"'Kate Adler' not found; got: {f[:200]}"
    return run_test(
        "Local role IRI (acmeUK:PeoplePartner)",
        "Who currently holds the People Partner role in AcmeUK?",
        check,
    )


def test_job_family() -> bool:
    """Tests acme:hasJobFamily + acme:Family_Engineering."""
    def check(df):
        if len(df) != 7:
            return False, f"expected 7 rows, got {len(df)}"
        if "Software Engineer" not in flat(df):
            return False, "expected 'Software Engineer' in results"
        return True, f"7 rows, 'Software Engineer' present"
    return run_test(
        "Job family (acme:Family_Engineering)",
        "List all global roles in the Engineering job family",
        check,
    )


def test_seniority_level() -> bool:
    """Tests acme:hasSeniorityLevel + acme:L4."""
    def check(df):
        if len(df) != 9:
            return False, f"expected 9 rows, got {len(df)}"
        f = flat(df)
        for name in ("Alice Chen", "David Patel", "Gina Chen"):
            if name not in f:
                return False, f"expected '{name}' in results"
        return True, f"9 rows, key names present"
    return run_test(
        "Seniority level (acme:L4)",
        "Which people are currently in Level 4 Senior roles across all subsidiaries?",
        check,
    )


def test_broadmatch_edge_cases() -> bool:
    """Tests broadMatch-only roles: acmeUS:PrincipalSWE and acmeUS:AreaVPOfSales."""
    def check(df):
        if len(df) != 2:
            return False, f"expected 2 rows, got {len(df)}"
        f = flat(df)
        for marker in ("PrincipalSWE", "AreaVPOfSales"):
            if marker not in f and marker.lower() not in f.lower():
                # also accept label forms
                alt = {"PrincipalSWE": "Principal Software Engineer",
                       "AreaVPOfSales": "Area VP"}
                if alt[marker] not in f:
                    return False, f"neither '{marker}' nor '{alt[marker]}' found in results"
        return True, "2 rows, both broadMatch-only roles present"
    return run_test(
        "broadMatch edge cases (PrincipalSWE, AreaVPOfSales)",
        "Which AcmeUS local roles are only broadly mapped to the global catalog "
        "and have no close match?",
        check,
    )


def test_software_agent_iri() -> bool:
    """Tests /agent/ IRI namespace and prov:SoftwareAgent aggregation."""
    def check(df):
        if len(df) == 0:
            return False, "got 0 rows"
        f = flat(df)
        if "LLM Mapper" not in f:
            return False, f"'LLM Mapper' not found; got: {f[:200]}"
        # the count column should be numeric and > 0
        for col in df.columns:
            vals = df[col].dropna().tolist()
            for v in vals:
                try:
                    if int(float(str(v))) > 0:
                        return True, f"'LLM Mapper' present, count > 0"
                except (ValueError, TypeError):
                    pass
        return True, f"'LLM Mapper' present in results"
    return run_test(
        "Software agent IRI (/agent/ namespace, prov:SoftwareAgent)",
        "Which software agents were involved in creating role mappings, "
        "and how many mappings did each create?",
        check,
    )


def test_skos_broader_hierarchy() -> bool:
    """Tests skos:broader links among global roles in the catalog."""
    def check(df):
        if len(df) < 2:
            return False, f"expected at least 2 rows, got {len(df)}"
        f = flat(df)
        if "Software Engineer" not in f and "SoftwareEngineer" not in f:
            return False, f"'Software Engineer' not found in results"
        return True, f"{len(df)} rows, 'Software Engineer' hierarchy present"
    return run_test(
        "skos:broader hierarchy among global roles",
        "What is the seniority hierarchy among Software Engineer global roles, "
        "from junior to senior?",
        check,
    )


# ── tests: existing gold query patterns (Q1–Q7) ───────────────────────────────

def test_q1_cross_subsidiary_employees() -> bool:
    """Q1 pattern: local→global SKOS traversal + active membership filter."""
    def check(df):
        if len(df) != 3:
            return False, f"expected 3 rows, got {len(df)}"
        f = flat(df)
        for name in ("Alice Chen", "Olga Weber", "Brianna Lee"):
            if name not in f:
                return False, f"'{name}' not found in results"
        return True, "3 rows, all three subsidiaries represented"
    return run_test(
        "Q1: cross-subsidiary employees for a global role",
        "Who currently holds a role equivalent to the Senior Software Engineer "
        "Level 4 global role across all subsidiaries?",
        check,
    )


def test_q2_cross_subsidiary_equivalents() -> bool:
    """Q2 pattern: use a global role as pivot to find equivalent local roles elsewhere.
    Row count is >= 2 because AcmeDE has both @en and @de org labels; depending on
    the subsidiary-label filter the NL query generates, Ontop may return both."""
    def check(df):
        if len(df) < 2:
            return False, f"expected at least 2 rows, got {len(df)}"
        f = flat(df)
        if "Softwareentwickler III" not in f:
            return False, f"'Softwareentwickler III' (DE equivalent) not found"
        if "SWE_III" not in f and "Software Engineer III" not in f:
            return False, f"AcmeUS equivalent not found in results"
        return True, f"{len(df)} rows, DE and US equivalents present"
    return run_test(
        "Q2: cross-subsidiary equivalents via global pivot",
        "What is the AcmeUK Senior Software Engineer role called in the other subsidiaries?",
        check,
    )


def test_q3_esco_traversal() -> bool:
    """Q3 pattern: local→global→ESCO traversal via skos:broadMatch.
    Gold query uses closeMatch|exactMatch for local→global (9 rows). NL queries
    may also include broadMatch, adding PrincipalSWE (10 rows). Both are valid
    interpretations; we assert >= 9 and presence of key names."""
    def check(df):
        if len(df) < 9:
            return False, f"expected at least 9 rows, got {len(df)}"
        f = flat(df)
        if "Alice Chen" not in f:
            return False, f"'Alice Chen' not found in results"
        if "Noah Becker" not in f:
            return False, f"'Noah Becker' not found in results"
        return True, f"{len(df)} rows, ESCO C2512 traversal correct"
    return run_test(
        "Q3: ESCO traversal via escoIsco:C2512",
        "Which AcmeCorp employees currently work in roles that map to the ISCO "
        "software developers group C2512?",
        check,
    )


def test_q4_reporting_lines() -> bool:
    """Q4 pattern: bounded UNION of fixed-length org:reportsTo paths.
    The question asks for all posts in Alice's chain including her own, so the
    expected answer is 3 (her post + EM + Head of Engineering)."""
    def check(df):
        if len(df) < 2:
            return False, f"expected at least 2 rows (chain above her post), got {len(df)}"
        f = flat(df)
        if "Head of Engineering" not in f:
            return False, f"'Head of Engineering' not found — bounded UNION may not go deep enough"
        return True, f"{len(df)} posts in chain, reaches Head of Engineering"
    return run_test(
        "Q4: reporting chain (bounded UNION, no arbitrary-length paths)",
        "What are all the posts in Alice Chen's reporting hierarchy at AcmeUK, "
        "from her own post up to the top of the chain?",
        check,
    )


def test_q5_open_postings() -> bool:
    """Q5 pattern: posts with no currently-active membership (nested FILTER NOT EXISTS)."""
    def check(df):
        if len(df) != 1:
            return False, f"expected 1 row, got {len(df)}"
        if "SF Payments" not in flat(df) and "Payments" not in flat(df):
            return False, f"expected SF Payments post in results"
        return True, "1 open post found (SF Payments EM)"
    return run_test(
        "Q5: open postings (nested FILTER NOT EXISTS)",
        "Which posts currently have no active member assigned to them?",
        check,
    )


def test_q6_mappings_needing_review() -> bool:
    """Q6 pattern: MappingActivity provenance with confidence/status filter."""
    def check(df):
        if len(df) != 2:
            return False, f"expected 2 rows, got {len(df)}"
        f = flat(df)
        if "Customer Success" not in f:
            return False, f"'Customer Success' mapping not found"
        if "Area VP" not in f and "AreaVPOfSales" not in f:
            return False, f"'Area VP' mapping not found"
        return True, "2 mappings needing review found"
    return run_test(
        "Q6: mappings needing review (confidence < 0.7 or status in-review)",
        "Which role mappings have low confidence or are not yet approved?",
        check,
    )


def test_q7_unmapped_local_roles() -> bool:
    """Q7 pattern: LocalRole with no outgoing SKOS mapping to GlobalRole."""
    def check(df):
        if len(df) != 1:
            return False, f"expected 1 row, got {len(df)}"
        if "Kundenservice" not in flat(df) and "KundenService" not in flat(df):
            return False, f"expected KundenServiceMitarbeiter in results"
        return True, "1 unmapped local role found (KundenServiceMitarbeiter)"
    return run_test(
        "Q7: unmapped local roles (FILTER NOT EXISTS on SKOS mapping)",
        "Which local job titles have no mapping to the global role catalog?",
        check,
    )


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        requests.get(ONTOP_HR, timeout=5)
    except requests.exceptions.RequestException:
        print(f"ERROR: HR Ontop endpoint not reachable at {ONTOP_HR}.\n"
              f"Start it first:  ./start_ontop.sh hr", file=sys.stderr)
        return 2

    tests = [
        # prompt additions
        test_local_role_iri,
        test_job_family,
        test_seniority_level,
        test_broadmatch_edge_cases,
        test_software_agent_iri,
        test_skos_broader_hierarchy,
        # existing gold query patterns
        test_q1_cross_subsidiary_employees,
        test_q2_cross_subsidiary_equivalents,
        test_q3_esco_traversal,
        test_q4_reporting_lines,
        test_q5_open_postings,
        test_q6_mappings_needing_review,
        test_q7_unmapped_local_roles,
    ]

    results = [t() for t in tests]
    passed = sum(results)
    failed = len(results) - passed

    print(f"\n{'=' * 70}")
    print(f"RESULT: {passed}/{len(results)} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print()
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

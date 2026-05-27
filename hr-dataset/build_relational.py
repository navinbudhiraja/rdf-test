#!/usr/bin/env python3
"""Convert the AcmeCorp HR Turtle dataset into a relational schema (data/hr.sql).

One-off build tool. Loads the 8 data Turtle files into an rdflib graph, extracts
rows, and writes ../data/hr.sql (DDL + INSERTs). Ontop later maps these tables back
to the original virtual RDF graph via ../ontop/hr.obda, so the IRIs/codes below are
chosen so the OBDA templates can reconstruct the exact original IRIs.

The original Turtle is the source of truth; rerun this whenever it changes:
    pip install rdflib
    python hr-dataset/build_relational.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from rdflib import Graph, Namespace, RDF, RDFS
    from rdflib.namespace import SKOS, FOAF
except ImportError:
    print("ERROR: rdflib is not installed. Run:  pip install rdflib", file=sys.stderr)
    sys.exit(1)

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "hr.sql"

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

# Namespaces
ACME = Namespace("https://acme.example/ontology/")
ACME_G = Namespace("https://acme.example/global/role/")
ACME_UK = Namespace("https://acme.example/uk/role/")
ACME_DE = Namespace("https://acme.example/de/role/")
ACME_US = Namespace("https://acme.example/us/role/")
ORGU = Namespace("https://acme.example/org/")
PERSON = Namespace("https://acme.example/person/")
POST = Namespace("https://acme.example/post/")
MEM = Namespace("https://acme.example/membership/")
MAPACT = Namespace("https://acme.example/mapping/activity/")
ORG = Namespace("http://www.w3.org/ns/org#")
PROV = Namespace("http://www.w3.org/ns/prov#")
TIME = Namespace("http://www.w3.org/2006/time#")
ESCO_BASE = "http://data.europa.eu/esco/"
ACME_BASE = "https://acme.example/"

LOCAL_NS = {"uk": str(ACME_UK), "de": str(ACME_DE), "us": str(ACME_US)}

SKOS_MATCH = {
    SKOS.exactMatch: "exactMatch",
    SKOS.closeMatch: "closeMatch",
    SKOS.broadMatch: "broadMatch",
    SKOS.narrowMatch: "narrowMatch",
    SKOS.relatedMatch: "relatedMatch",
}


_PURE_FRAGMENT = re.compile(r'^\s*"[^"]*"\s*$')


def _merge_adjacent_literals(text: str) -> str:
    """Merge runs of adjacent Turtle string literals into one literal (in memory only).

    The shipped Turtle splits long descriptions/comments across several adjacent
    quoted strings, which is invalid Turtle (no string concatenation). We join each
    such run before parsing. Source files are never modified. Only descriptions/
    comments/definitions are affected — none are projected by the 7 gold queries.
    """
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        if _PURE_FRAGMENT.match(lines[i]):
            run, j = [], i
            while j < len(lines) and lines[j].lstrip().startswith('"'):
                run.append(lines[j])
                if not _PURE_FRAGMENT.match(lines[j]):  # terminating fragment (has @lang/;/.)
                    j += 1
                    break
                j += 1
            if len(run) >= 2:
                indent = re.match(r'^(\s*)', run[0]).group(1)
                contents = [f[f.find('"') + 1:f.rfind('"')] for f in run]
                suffix = run[-1][run[-1].rfind('"') + 1:]
                out.append(f'{indent}"{"".join(contents)}"{suffix}')
                i = j
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out) + "\n"


def load_graph(base_dir: Path | None = None) -> "Graph":
    """Load the 8 HR data Turtle files into one rdflib graph (with literal-merge fix)."""
    base = base_dir or HERE
    g = Graph()
    for fname in DATA_FILES:
        text = (base / fname).read_text(encoding="utf-8")
        g.parse(data=_merge_adjacent_literals(text), format="turtle")
    return g


def ln(uri, ns: str) -> str:
    """Local name: the part of `uri` after namespace `ns`."""
    s = str(uri)
    assert s.startswith(ns), f"{s} not in namespace {ns}"
    return s[len(ns):]


def subsidiary_of(role_uri) -> tuple[str, str]:
    """(subsidiary_code, localname) for a local-role IRI."""
    s = str(role_uri)
    for code, ns in LOCAL_NS.items():
        if s.startswith(ns):
            return code, s[len(ns):]
    raise ValueError(f"not a local role IRI: {s}")


# ---- SQL emission helpers --------------------------------------------------

def q(v) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def num(v) -> str:
    return "NULL" if v is None else str(v)


def insert(table: str, cols: list[str], rows: list[tuple]) -> str:
    if not rows:
        return f"-- (no rows for {table})\n"
    out = []
    collist = ", ".join(cols)
    for r in rows:
        out.append(f"INSERT INTO {table} ({collist}) VALUES ({', '.join(r)});")
    return "\n".join(out) + "\n"


DDL = """\
-- =============================================================================
-- AcmeCorp HR relational schema  (generated by hr-dataset/build_relational.py)
--
-- Ontop maps these tables back to the original RDF graph via ontop/hr.obda.
-- DO NOT EDIT BY HAND — regenerate from the Turtle source instead.
-- =============================================================================

DROP TABLE IF EXISTS membership;
DROP TABLE IF EXISTS post;
DROP TABLE IF EXISTS person;
DROP TABLE IF EXISTS mapping_agent;
DROP TABLE IF EXISTS esco_anchor;
DROP TABLE IF EXISTS role_mapping;
DROP TABLE IF EXISTS local_role;
DROP TABLE IF EXISTS global_role;
DROP TABLE IF EXISTS job_family;
DROP TABLE IF EXISTS seniority_level;
DROP TABLE IF EXISTS org_label;
DROP TABLE IF EXISTS organization;

CREATE TABLE organization (
    org_id        VARCHAR PRIMARY KEY,   -- e.g. 'AcmeUK'  -> orgU:AcmeUK
    kind          VARCHAR,               -- 'group' | 'subsidiary'
    parent_org_id VARCHAR                -- org:subOrganizationOf (NULL for the group)
);

CREATE TABLE org_label (
    org_id VARCHAR,
    label  VARCHAR,
    lang   VARCHAR,
    PRIMARY KEY (org_id, lang)
);

CREATE TABLE seniority_level (
    sl_code VARCHAR PRIMARY KEY,         -- 'L1'..'L9'  -> acme:L1..acme:L9
    label   VARCHAR,
    ordinal INTEGER
);

CREATE TABLE job_family (
    jf_code VARCHAR PRIMARY KEY,         -- 'Family_Engineering' -> acme:Family_Engineering
    label   VARCHAR
);

CREATE TABLE global_role (
    gr_code         VARCHAR PRIMARY KEY, -- 'SoftwareEngineerL4' -> acmeG:SoftwareEngineerL4
    pref_label      VARCHAR,
    definition      VARCHAR,
    jf_code         VARCHAR,
    sl_code         VARCHAR,
    broader_gr_code VARCHAR              -- skos:broader (NULL if none)
);

CREATE TABLE local_role (
    subsidiary VARCHAR,                  -- 'uk' | 'de' | 'us'  -> acmeUK/DE/US namespace
    localname  VARCHAR,                  -- e.g. 'SeniorSoftwareEngineer'
    pref_label VARCHAR,
    pref_lang  VARCHAR,
    alt_label  VARCHAR,
    alt_lang   VARCHAR,
    scope_note VARCHAR,
    scope_lang VARCHAR,
    PRIMARY KEY (subsidiary, localname)
);

CREATE TABLE role_mapping (
    map_id         VARCHAR PRIMARY KEY,  -- 'uk_001' -> mapAct:uk_001
    subsidiary     VARCHAR,              -- of the local role
    lr_localname   VARCHAR,              -- local role (prov:used)
    gr_code        VARCHAR,              -- global role (prov:generated)
    match_type     VARCHAR,              -- 'closeMatch' | 'broadMatch' | ...
    confidence     DECIMAL(3,2),
    review_status  VARCHAR,
    mapping_method VARCHAR,
    mapped_at      VARCHAR               -- xsd:dateTime lexical form
);

CREATE TABLE mapping_agent (
    map_id      VARCHAR,
    agent_id    VARCHAR,                 -- e.g. 'person/jordan-kim','agent/llm-mapper-v2'
    agent_label VARCHAR,
    agent_kind  VARCHAR,                 -- 'Person' | 'SoftwareAgent'
    PRIMARY KEY (map_id, agent_id)
);

CREATE TABLE esco_anchor (
    gr_code    VARCHAR,
    match_type VARCHAR,                  -- 'broadMatch' | 'closeMatch' | 'relatedMatch' | ...
    esco_uri   VARCHAR,                  -- full external ESCO/ISCO URI
    PRIMARY KEY (gr_code, esco_uri, match_type)
);

CREATE TABLE person (
    person_id VARCHAR PRIMARY KEY,       -- 'alice_01' -> p:alice_01
    name      VARCHAR
);

CREATE TABLE post (
    post_id            VARCHAR PRIMARY KEY,  -- 'uk_001' -> post:uk_001
    label              VARCHAR,
    label_lang         VARCHAR,
    subsidiary         VARCHAR,              -- of org:role (local role namespace)
    role_localname     VARCHAR,              -- org:role
    org_id             VARCHAR,              -- org:postIn
    reports_to_post_id VARCHAR               -- org:reportsTo (NULL if top)
);

CREATE TABLE membership (
    mem_id              VARCHAR PRIMARY KEY,  -- 'alice_01','mia_01_past' -> m:...
    person_id           VARCHAR,              -- org:member
    org_id              VARCHAR,              -- org:organization
    subsidiary          VARCHAR,              -- of org:role
    role_localname      VARCHAR,              -- org:role
    via_post_id         VARCHAR,              -- acme:viaPost (NULL if none)
    begin_date          DATE,                 -- time:hasBeginning/inXSDDate
    end_date            DATE,                 -- time:hasEnd/inXSDDate (NULL = active)
    linked_from_person  BOOLEAN               -- person org:hasMembership m  (false for Eve's closed seat)
);
"""


def build() -> None:
    g = load_graph()

    sections: list[str] = [DDL]
    counts: dict[str, int] = {}

    # -- organization + org_label --------------------------------------------
    org_rows, label_rows = [], []
    orgs = set(g.subjects(RDF.type, ORG.FormalOrganization)) | set(g.subjects(RDF.type, ACME.Subsidiary))
    for o in orgs:
        oid = ln(o, str(ORGU))
        kind = "subsidiary" if (o, RDF.type, ACME.Subsidiary) in g else "group"
        parent = g.value(o, ORG.subOrganizationOf)
        parent_id = ln(parent, str(ORGU)) if parent else None
        org_rows.append((q(oid), q(kind), q(parent_id)))
        for lbl in g.objects(o, SKOS.prefLabel):
            label_rows.append((q(oid), q(str(lbl)), q(lbl.language)))
    sections.append(insert("organization", ["org_id", "kind", "parent_org_id"], sorted(org_rows)))
    sections.append(insert("org_label", ["org_id", "label", "lang"], sorted(label_rows)))
    counts["organization"], counts["org_label"] = len(org_rows), len(label_rows)

    # -- seniority_level -----------------------------------------------------
    sl_rows = []
    for sl in g.subjects(RDF.type, ACME.SeniorityLevel):
        sl_rows.append((q(ln(sl, str(ACME))), q(str(g.value(sl, RDFS.label))),
                        num(int(g.value(sl, ACME.levelOrdinal)))))
    sections.append(insert("seniority_level", ["sl_code", "label", "ordinal"], sorted(sl_rows)))
    counts["seniority_level"] = len(sl_rows)

    # -- job_family ----------------------------------------------------------
    jf_rows = []
    for jf in g.subjects(RDF.type, ACME.JobFamily):
        jf_rows.append((q(ln(jf, str(ACME))), q(str(g.value(jf, SKOS.prefLabel)))))
    sections.append(insert("job_family", ["jf_code", "label"], sorted(jf_rows)))
    counts["job_family"] = len(jf_rows)

    # -- global_role ---------------------------------------------------------
    gr_rows = []
    for gr in g.subjects(RDF.type, ACME.GlobalRole):
        definition = g.value(gr, SKOS.definition)
        broader = g.value(gr, SKOS.broader)
        gr_rows.append((
            q(ln(gr, str(ACME_G))),
            q(str(g.value(gr, SKOS.prefLabel))),
            q(str(definition) if definition else None),
            q(ln(g.value(gr, ACME.hasJobFamily), str(ACME))),
            q(ln(g.value(gr, ACME.hasSeniorityLevel), str(ACME))),
            q(ln(broader, str(ACME_G)) if broader else None),
        ))
    sections.append(insert("global_role",
                           ["gr_code", "pref_label", "definition", "jf_code", "sl_code", "broader_gr_code"],
                           sorted(gr_rows)))
    counts["global_role"] = len(gr_rows)

    # -- local_role ----------------------------------------------------------
    lr_rows = []
    for lr in g.subjects(RDF.type, ACME.LocalRole):
        sub, name = subsidiary_of(lr)
        pref = g.value(lr, SKOS.prefLabel)
        alt = g.value(lr, SKOS.altLabel)
        scope = g.value(lr, SKOS.scopeNote)
        lr_rows.append((q(sub), q(name), q(str(pref)), q(pref.language),
                        q(str(alt) if alt else None), q(alt.language if alt else None),
                        q(str(scope) if scope else None), q(scope.language if scope else None)))
    sections.append(insert("local_role",
                           ["subsidiary", "localname", "pref_label", "pref_lang",
                            "alt_label", "alt_lang", "scope_note", "scope_lang"],
                           sorted(lr_rows)))
    counts["local_role"] = len(lr_rows)

    # -- role_mapping + mapping_agent ----------------------------------------
    rm_rows, ma_rows = [], []
    for act in g.subjects(RDF.type, ACME.MappingActivity):
        map_id = ln(act, str(MAPACT))
        local = g.value(act, PROV.used)
        glob = g.value(act, PROV.generated)
        sub, lr_name = subsidiary_of(local)
        gr_code = ln(glob, str(ACME_G))
        # match type = the skos relation triple between local and global
        match_type = next((name for pred, name in SKOS_MATCH.items() if (local, pred, glob) in g), None)
        conf = g.value(act, ACME.confidence)
        rm_rows.append((
            q(map_id), q(sub), q(lr_name), q(gr_code), q(match_type),
            num(conf), q(str(g.value(act, ACME.reviewStatus))),
            q(str(g.value(act, ACME.mappingMethod))), q(str(g.value(act, PROV.atTime))),
        ))
        for agent in g.objects(act, PROV.wasAssociatedWith):
            agent_id = ln(agent, ACME_BASE)
            kind = "SoftwareAgent" if (agent, RDF.type, PROV.SoftwareAgent) in g else "Person"
            ma_rows.append((q(map_id), q(agent_id), q(str(g.value(agent, RDFS.label))), q(kind)))
    sections.append(insert("role_mapping",
                           ["map_id", "subsidiary", "lr_localname", "gr_code", "match_type",
                            "confidence", "review_status", "mapping_method", "mapped_at"],
                           sorted(rm_rows)))
    sections.append(insert("mapping_agent", ["map_id", "agent_id", "agent_label", "agent_kind"],
                           sorted(ma_rows)))
    counts["role_mapping"], counts["mapping_agent"] = len(rm_rows), len(ma_rows)

    # -- esco_anchor ---------------------------------------------------------
    ea_rows = []
    for gr in g.subjects(RDF.type, ACME.GlobalRole):
        gr_code = ln(gr, str(ACME_G))
        for pred, name in SKOS_MATCH.items():
            for obj in g.objects(gr, pred):
                if str(obj).startswith(ESCO_BASE):
                    ea_rows.append((q(gr_code), q(name), q(str(obj))))
    sections.append(insert("esco_anchor", ["gr_code", "match_type", "esco_uri"], sorted(ea_rows)))
    counts["esco_anchor"] = len(ea_rows)

    # -- person --------------------------------------------------------------
    p_rows = []
    for p in g.subjects(RDF.type, FOAF.Person):
        p_rows.append((q(ln(p, str(PERSON))), q(str(g.value(p, FOAF.name)))))
    sections.append(insert("person", ["person_id", "name"], sorted(p_rows)))
    counts["person"] = len(p_rows)

    # -- post ----------------------------------------------------------------
    post_rows = []
    for ps in g.subjects(RDF.type, ORG.Post):
        label = g.value(ps, SKOS.prefLabel)
        role = g.value(ps, ORG.role)
        sub, role_name = subsidiary_of(role)
        org_in = g.value(ps, ORG.postIn)
        reports = g.value(ps, ORG.reportsTo)
        post_rows.append((
            q(ln(ps, str(POST))), q(str(label)), q(label.language),
            q(sub), q(role_name), q(ln(org_in, str(ORGU))),
            q(ln(reports, str(POST)) if reports else None),
        ))
    sections.append(insert("post",
                           ["post_id", "label", "label_lang", "subsidiary", "role_localname",
                            "org_id", "reports_to_post_id"],
                           sorted(post_rows)))
    counts["post"] = len(post_rows)

    # -- membership ----------------------------------------------------------
    def interval_date(interval, which):
        node = g.value(interval, which)
        return str(g.value(node, TIME.inXSDDate)) if node else None

    mem_rows = []
    for m in g.subjects(RDF.type, ORG.Membership):
        role = g.value(m, ORG.role)
        sub, role_name = subsidiary_of(role)
        member = g.value(m, ORG.member)
        via = g.value(m, ACME.viaPost)
        interval = g.value(m, ORG.memberDuring)
        begin = interval_date(interval, TIME.hasBeginning)
        end = interval_date(interval, TIME.hasEnd)
        linked = "TRUE" if (member, ORG.hasMembership, m) in g else "FALSE"
        mem_rows.append((
            q(ln(m, str(MEM))), q(ln(member, str(PERSON))),
            q(ln(g.value(m, ORG.organization), str(ORGU))), q(sub), q(role_name),
            q(ln(via, str(POST)) if via else None), q(begin), q(end), linked,
        ))
    sections.append(insert("membership",
                           ["mem_id", "person_id", "org_id", "subsidiary", "role_localname",
                            "via_post_id", "begin_date", "end_date", "linked_from_person"],
                           sorted(mem_rows)))
    counts["membership"] = len(mem_rows)

    OUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {OUT}  ({len(g)} source triples)")
    for t, n in counts.items():
        print(f"  {t:18}{n:>5} rows")


if __name__ == "__main__":
    build()

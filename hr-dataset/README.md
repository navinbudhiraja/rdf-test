# AcmeCorp HR Ontology — Test Dataset

A realistic synthetic dataset for testing the multi-subsidiary HR ontology architecture
described in the accompanying research report. It demonstrates the canonical pattern:
local subsidiary vocabularies + a global enterprise reference vocabulary + SKOS mappings
between them, all anchored to real ESCO/ISCO concept URIs where appropriate.

The data describes a fictional multinational, **AcmeCorp**, with three subsidiaries:

| Subsidiary | Country | Language(s) | Style of role naming                         |
| ---------- | ------- | ----------- | -------------------------------------------- |
| AcmeUK     | UK      | en-GB       | British titles, "Senior X", "Lead Y", "Head of Z" |
| AcmeDE     | DE      | de + en     | German titles with seniority suffixes (II, III, IV) |
| AcmeUS     | US      | en-US       | US-style ladder (LX levels), "VP", "Director" |

Each subsidiary uses different words for what is often the same global role.
The dataset shows how all three are mapped into one harmonized enterprise vocabulary,
and that vocabulary in turn is mapped to ESCO so it can be reused across standards.

## Files

```
hr-dataset/
├── README.md                       <- this file
├── 01_ontology.ttl                 <- the schema (TBox): custom classes/properties
├── 02_global_reference.ttl         <- AcmeCorp's global role catalog (~25 roles)
├── 03_local_acme_uk.ttl            <- AcmeUK's local job-title vocabulary
├── 04_local_acme_de.ttl            <- AcmeDE's local job-title vocabulary
├── 05_local_acme_us.ttl            <- AcmeUS's local job-title vocabulary
├── 06_mappings.ttl                 <- SKOS mappings: local <-> global, with provenance
├── 07_esco_anchors.ttl             <- mappings from global roles to real ESCO URIs
├── 08_instance_data.ttl            <- people, posts, memberships (~40 employees)
├── 09_shapes.shacl.ttl             <- SHACL shapes for validating the data
├── queries/
│   ├── 01_global_role_to_employees.rq
│   ├── 02_cross_subsidiary_equivalents.rq
│   ├── 03_skill_to_people_via_esco.rq
│   ├── 04_reporting_lines.rq
│   ├── 05_open_postings_by_role.rq
│   ├── 06_mappings_needing_review.rq
│   └── 07_unmapped_local_roles.rq
└── tests/
    ├── expected_results.md         <- what each query should return
    └── load_and_query.py           <- end-to-end test harness (requires rdflib)
```

## Quick start

### Option A — load into your own triple store
The files are standard Turtle. Load them in this order:

1. `01_ontology.ttl`
2. `02_global_reference.ttl`
3. `03_local_acme_uk.ttl`, `04_local_acme_de.ttl`, `05_local_acme_us.ttl`
4. `06_mappings.ttl`
5. `07_esco_anchors.ttl`
6. `08_instance_data.ttl`

Then load `09_shapes.shacl.ttl` as a SHACL shapes graph and validate.

Tested with: GraphDB 10.x, Apache Jena Fuseki, Stardog, Blazegraph, rdflib 7.x.

### Option B — Python with rdflib
```bash
pip install rdflib pyshacl
python tests/load_and_query.py
```

The harness loads everything, runs each query in `queries/`, and prints a pass/fail
summary against the expected results in `tests/expected_results.md`.

## What this dataset is designed to test

1. **Loading and parsing.** Does your tool round-trip all 9 files without errors?
2. **SKOS mapping traversal.** Can `skos:closeMatch` / `broadMatch` / `narrowMatch`
   be followed in queries (property paths)?
3. **Cross-subsidiary equivalence.** Given a global role, can you find every
   employee holding any locally-equivalent role across all subsidiaries?
4. **External anchoring.** Can you query through to ESCO URIs and back?
5. **The n-ary `org:Membership` pattern.** Can you correctly join Person → Post →
   Role → Organization → time-interval?
6. **Provenance.** Can you list mappings that need review (low confidence,
   stale author, missing approval)?
7. **SHACL validation.** Do the shapes catch deliberately-introduced errors?
8. **OWL reasoning (optional).** With a reasoner enabled, do role-hierarchy
   inferences appear? E.g. an employee in a `narrowMatch` of `SoftwareEngineer`
   should answer a query for `SoftwareEngineer` if you elect to treat
   `skos:narrowMatch` as a subclass-like relation in your application layer.

## Deliberate "gotchas" embedded in the data

To make tests meaningful, the dataset includes a small number of realistic
imperfections you would find in real enterprise data:

- One AcmeDE role (`acmeDE:KundenServiceMitarbeiter`) is **unmapped** — your query
  in `07_unmapped_local_roles.rq` should find it.
- Two mappings have `acme:confidence < 0.7` and should appear in
  `06_mappings_needing_review.rq`.
- One person (`acme:person/eve_05`) holds an open Post (no membership) — this
  tests the `05_open_postings_by_role.rq` query.
- One AcmeUS role uses a `skos:broadMatch` (rather than `closeMatch`) to a global
  role to reflect a real seniority mismatch.
- The SHACL shapes will fail if you delete the `prov:wasAssociatedWith` triple
  from any mapping activity in `06_mappings.ttl` — try it.

## Notes on ESCO references

The ESCO URIs used in `07_esco_anchors.ttl` are **real, live concept URIs** from
the published ESCO classification (v1.2.x at the time of writing). They resolve
on the ESCO portal at:

```
https://esco.ec.europa.eu/en/classification/occupation?uri=<URI>
```

If you want to materialise the ESCO concepts as full graph data (their preferred
labels in 28 languages, descriptions, alternative labels, ISCO mappings, related
skills), download the official ESCO RDF dump from
<https://esco.ec.europa.eu/en/use-esco/download> and load it alongside this
dataset. The mappings in `07_esco_anchors.ttl` will then "light up" with full
ESCO context.

## License

Synthetic data. CC0 / public domain — use freely.

ESCO concept URIs are referenced but not redistributed; ESCO itself is published
under the European Union Public Licence (EUPL).

# HR SPARQL System Prompt Design

This document explains how `_HR_SPARQL_SYSTEM` in `src/nl_translator.py` was constructed:
what was pulled from each source file, why those things specifically, and where the prompt
is known to fall short.

---

## Sources

The prompt is assembled from three sources: the TBox (`ontop/hr.ttl`), the OBDA mappings
(`ontop/hr.obda`), and the gold query set (`hr-dataset/queries/*.rq`). Each contributes
a different layer.

### 1. TBox (`ontop/hr.ttl`)

The TBox declares classes and properties. Every `owl:Class` declaration became a **Classes**
entry; every `owl:ObjectProperty` and `owl:DatatypeProperty` became a **Key properties**
entry. The TBox is the right source for this layer because it is the schema-level contract
between the ontology designer and the query author.

Standard-vocabulary classes that appear in the mappings but are not redeclared in `hr.ttl`
(`org:Post`, `org:Membership`, `foaf:Person`) were added manually, because Claude needs
to know they exist and what role they play.

### 2. OBDA mappings (`ontop/hr.obda`)

The OBDA file has a `source` (SQL) and a `target` (RDF triple pattern) for each mapping.
Claude generates SPARQL and never sees the relational side, so only the `target` blocks
are directly relevant. Three things were extracted from them:

**IRI templates.** The template syntax (`acmeG:{gr_code}`, `p:{person_id}`, `m:{mem_id}`,
etc.) reveals what IRI shapes exist in the graph and which prefix maps to which concept.
Without these, Claude invents plausible-but-wrong IRIs. These were turned into the
**IRI patterns** section verbatim.

**Predicate direction and subject/object types.** A triple like
`acmeUK:{localname} skos:closeMatch acmeG:{gr_code}` shows that `skos:closeMatch` goes
from a local-role IRI to a global-role IRI, not the other way around. This determines
which direction a SPARQL pattern must traverse. Every distinct predicate + subject/object
combination was checked for this.

**Optional vs mandatory predicates.** A mapping whose `source` query has a
`WHERE column IS NOT NULL` clause means the corresponding predicate is absent for some
nodes. For example, `membership-interval-end` has `WHERE end_date IS NOT NULL`, which is
why the active-membership pattern in the prompt uses
`FILTER NOT EXISTS { ?iv time:hasEnd ?e }` rather than asserting `time:hasEnd` directly.

The `source` SQL is not included in the prompt — Claude does not need to know the
relational schema to write SPARQL. The SQL was only read to understand conditionality.

**Prefixes.** The `[PrefixDeclaration]` block was copied verbatim. Every prefix that
appears in a mapping target needed to be in the prompt so Claude would use the exact
namespace strings.

### 3. Gold queries (`hr-dataset/queries/*.rq`)

The seven gold queries were adapted into the **Example queries** section. Data-specific
`BIND` statements (e.g. `BIND(acmeG:SoftwareEngineerL4 AS ?targetRole)`) were removed
so the examples show query *shape*, not one particular question. The mapping is:

| Prompt example | Gold query |
|---|---|
| Employees holding a role equivalent to a global role | `01_global_role_to_employees.rq` |
| Reporting line (bounded UNION) | `04_reporting_lines.rq` |
| Open postings | `05_open_postings_by_role.rq` |
| Mappings needing review | `06_mappings_needing_review.rq` |
| Unmapped local roles | `07_unmapped_local_roles.rq` |

`02_cross_subsidiary_equivalents.rq` and `03_skill_to_people_via_esco.rq` are not
represented as standalone examples but their patterns (SKOS pivot, ESCO traversal) are
covered by the rules and properties sections.

---

## Rules section

Every rule in the **Rules** section encodes a constraint discovered through testing
against the live Ontop 5.5.0 endpoint, not from reading documentation.

**No arbitrary-length property paths (`*`, `+`).** Ontop 5.5.0 does not support them.
The original `04_reporting_lines.rq` used `org:reportsTo*` and silently returned nothing.
The rule was added so Claude would never generate the unsupported pattern; the example
query shows the bounded-UNION workaround explicitly.

**Language tag casing.** Ontop lowercases all language tags at output time: `@en-GB`
becomes `en-gb`. Queries that compared with `lang(?x) IN ("en-GB", "en-US")` dropped
every UK and US result because the tags never matched. The fix was applied to the gold
queries themselves and encoded as a hard rule: always use `LCASE(lang(?x))` and always
compare against lowercase strings.

**SKOS semantics, not `owl:sameAs`.** Local roles are *approximately* aligned to global
roles, not identical. Without this rule, Claude tends to generate equality filters or
sameAs-style inference for cross-subsidiary questions, which returns nothing.

**Sequence (`/`), alternative (`|`), and inverse (`^`) paths are fine.** This positive
statement was added explicitly because the prohibition on `*`/`+` might otherwise cause
Claude to avoid all property path syntax, which would make it unable to express the
active-membership and reporting-chain patterns compactly.

---

## Sufficiency

Sufficiency was assessed empirically, not proved. The round-trip test
(`hr-dataset/tests/verify_ontop.py`) runs each gold query against both the rdflib oracle
(the original Turtle) and the Ontop endpoint and asserts the result sets match. If Claude
can generate correct SPARQL for all seven gold-query patterns given the prompt, the prompt
is considered sufficient for that scope.

---

## Known limitations

**Agent IRI pattern is missing.** The `mapping-activity-agent` mapping mints agent IRIs
as `<https://acme.example/{agent_id}>` — a bare IRI with no named prefix. That pattern
does not appear in the IRI patterns section. A question about which agent approved a
mapping would likely produce a wrong IRI shape or fail to return results.

**`acme:levelOrdinal` has no example.** `acme:levelOrdinal xsd:integer` is declared in
the TBox and mapped, but no gold query uses it. Claude may get the datatype wrong or
omit it when a question compares seniority levels numerically.

**Multi-language org labels not explicitly called out.** The org-label mappings produce
`skos:prefLabel` with `@en`, `@en-GB`, `@en-US`, and `@de` tags depending on the row.
The prompt mentions the language-tag rule generally, but does not show an example
filtering org labels. A question that asks for org names in a specific language could
produce a subtly wrong FILTER.

**Cross-subsidiary equivalence (Q2) has no example.** The pattern — use a global role
as a pivot to find all local roles across subsidiaries that share the same mapping — is
not shown in the examples section. Claude may conflate it with Q1's pattern (find people
via a global role) and produce a query that returns people rather than role names.

**ESCO traversal (Q3) has no example.** The pattern connecting local roles to external
ESCO/ISCO URIs via `skos:broadMatch|skos:closeMatch|skos:relatedMatch` on global roles is
described in the properties section but not demonstrated. The lack of a concrete ESCO URI
example means Claude may not know what a valid ESCO IRI looks like.

**The prompt was validated against seven queries.** Any question whose graph pattern falls
outside those seven shapes is best-effort. The prompt is not a complete specification of
the graph — it is a curated subset sufficient for the patterns the gold set exercises.

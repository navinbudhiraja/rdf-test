# Expected Results

This file documents what each SPARQL query in `queries/` should return when
run against the loaded dataset. The Python test harness
(`tests/load_and_query.py`) checks the live output against these expectations.

---

## Q1 — Global role to employees

**Default bound role:** `acmeG:SoftwareEngineerL4` (Senior Software Engineer)

Should return **3 people**, one from each subsidiary, all currently active:

| Person          | Subsidiary             | Local role                  |
| --------------- | ---------------------- | --------------------------- |
| Alice Chen      | Acme UK Ltd            | Senior Software Engineer    |
| Olga Weber      | Acme Deutschland GmbH  | Softwareentwickler III      |
| Brianna Lee     | Acme USA Inc.          | Software Engineer III       |

This demonstrates that one query against the global concept returns
employees with three different local titles in three subsidiaries.

---

## Q2 — Cross-subsidiary equivalents

**Default bound input:** `acmeUK:SeniorSoftwareEngineer`

Should return **2 equivalent roles** in other subsidiaries:

| Equivalent role              | Scheme                |
| ---------------------------- | --------------------- |
| Softwareentwickler III       | AcmeDE Role Scheme    |
| Software Engineer III        | AcmeUS Role Scheme    |

All three map to `acmeG:SoftwareEngineerL4`, but only the two non-UK ones
should be in the result set (the input is filtered out).

---

## Q3 — ESCO traversal

**Default bound ESCO target:** `escoIsco:C2512` (ISCO Software developers)

Should return **9 people** — every active software engineer across all
subsidiaries, regardless of seniority. AcmeUK contributes 3 (Alice, Bob,
Carol), AcmeDE contributes 3 (Noah, Olga, Peter), AcmeUS contributes 3
(Aiden, Brianna, Carlos). The `acmeUS:PrincipalSWE` role doesn't appear
because Dana's role uses `skos:broadMatch` (not closeMatch/exactMatch) to
the global concept, and the query only follows closeMatch/exactMatch.

(If you change the query to also follow `skos:broadMatch`, Dana Park will
appear too.)

---

## Q4 — Reporting line for Alice Chen

Should return Alice's full reporting chain:

| Post (en label)                            |
| ------------------------------------------ |
| Senior SWE, London Payments                |
| Engineering Manager, London Payments       |
| Head of Engineering, UK                    |

The chain walks `org:reportsTo*` from Alice's own post upward.

---

## Q5 — Open postings

Should return **exactly 1 row** — the Engineering Manager post in SF
Payments, vacated by Eve Martinez:

| Post                                | Subsidiary       | Local role              | Global role                  |
| ----------------------------------- | ---------------- | ----------------------- | ---------------------------- |
| Engineering Manager, SF Payments    | Acme USA Inc.    | Engineering Manager     | Engineering Manager, Level 6 |

---

## Q6 — Mappings needing review

Should return **exactly 2 rows** — the two deliberately low-confidence
mappings:

| Local role                       | Global role                          | Confidence | Status     |
| -------------------------------- | ------------------------------------ | ---------- | ---------- |
| Customer Success Associate       | Customer Support Representative L2   | 0.62       | in-review  |
| Area VP of Sales                 | VP of Sales, Level 8                 | 0.65       | in-review  |

---

## Q7 — Unmapped local roles

Should return **exactly 1 row** — the deliberately unmapped German role:

| Local role                  | Subsidiary             |
| --------------------------- | ---------------------- |
| Kundenservicemitarbeiter    | Acme Deutschland GmbH  |

---

## SHACL validation

Running the shapes in `09_shapes.shacl.ttl` against the data graph should
produce **exactly one violation** under default conditions:

- `acme:LocalRoleMappedShape` fires on `acmeDE:KundenServiceMitarbeiter`
  because that role has no outgoing SKOS mapping into the global catalog.

To verify SHACL more thoroughly:

1. Delete the `prov:wasAssociatedWith` triple from any MappingActivity in
   `06_mappings.ttl` — `acme:MappingActivityShape` should report a violation.
2. Change a confidence value to `1.5` — `acme:MappingActivityShape`
   `sh:maxInclusive 1` should report a violation.
3. Set a `acme:reviewStatus` to `"pending"` — should fail the `sh:in` check.

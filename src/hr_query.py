"""In-process HR query pipeline for the web chat.

The web app answers HR questions by calling this directly — it does NOT go through
the MCP server. (`mcp_server.py` remains the MCP surface for Claude Desktop; the web
app calling its own pipeline in-process avoids spawning/serializing through a
subprocess.) `run()` returns structured data so the UI can render tables/charts with
no markdown round-trip.

HR is SPARQL-only: translate the NL question to SPARQL and execute it against the HR
Ontop endpoint (:8081). Blocking (Claude call + HTTP) — callers in async contexts
should wrap it in `asyncio.to_thread`.
"""

from __future__ import annotations

import datasets
import nl_translator
import sparql_executor

# Ontology reference handed to the model as the `get_hr_schema` tool result. Kept in
# sync with the same text in `mcp_server.get_hr_schema` (Claude Desktop's copy).
SCHEMA = """\
## AcmeCorp HR Ontology (query with SPARQL via ask_hr)

A multinational with 3 subsidiaries (AcmeUK, AcmeDE, AcmeUS). Each subsidiary's
LOCAL job titles are mapped via SKOS to a GLOBAL role catalog, which is anchored
to ESCO/ISCO occupations.

### Prefixes
- acme:   https://acme.example/ontology/        (classes, properties)
- acmeG:  https://acme.example/global/role/      (global roles)
- acmeUK: / acmeDE: / acmeUS:  https://acme.example/{uk|de|us}/role/   (local roles)
- orgU:   https://acme.example/org/    p: …/person/    post: …/post/
- org: http://www.w3.org/ns/org#   skos: …/skos/core#   foaf:, prov:, time:
- escoIsco: http://data.europa.eu/esco/isco/   escoOcc: …/esco/occupation/

### Classes
- acme:GlobalRole, acme:LocalRole, acme:Subsidiary, acme:JobFamily,
  acme:SeniorityLevel (acme:L1..L9), acme:MappingActivity
- org:Post, org:Membership, foaf:Person

### Key relationships
- Local→global:  ?localRole skos:closeMatch|skos:broadMatch ?globalRole
- Global→ESCO:   ?globalRole skos:broadMatch|skos:closeMatch|skos:relatedMatch ?esco
- Role meta:     ?globalRole acme:hasJobFamily ?f ; acme:hasSeniorityLevel ?l
                 ?localRole acme:scopedTo ?subsidiary
- People/posts:  ?m a org:Membership ; org:member ?person ; org:organization ?sub ;
                 org:role ?localRole ; acme:viaPost ?post ; org:memberDuring ?iv
                 ?person org:hasMembership ?m ; foaf:name ?name
                 ?post org:reportsTo ?managerPost   (walk with org:reportsTo*)
                 ACTIVE membership = no time:hasEnd on its interval
- Provenance:    ?a a acme:MappingActivity ; prov:used ?lr ; prov:generated ?gr ;
                 acme:confidence ?c ; acme:reviewStatus ?s ; prov:wasAssociatedWith ?agent

### Labels
Language-tagged: AcmeUK/posts @en-GB, AcmeDE @de (+ @en on orgs), AcmeUS @en-US,
global roles @en. Use FILTER (lang(?l) IN ("en","en-GB","en-US","de")).

Data: ~40 employees · 48 local roles · 21 global roles · 47 mappings · 3 subsidiaries
"""


def run(question: str) -> dict:
    """Answer one HR question. Returns a structured result for the UI:

      {"sparql": str|None, "columns": [str], "rows": [dict], "rowCount": int,
       "error": str|None}

    `error` is set (and rows empty) on a translation failure or an unreachable HR
    endpoint; otherwise `error` is None and `rows` may be empty (a zero-row answer).
    """
    endpoint = datasets.get("hr")["sparql_endpoint"]

    try:
        sparql, _sql = nl_translator.translate(question, "hr")
    except RuntimeError as exc:
        return {"sparql": None, "columns": [], "rows": [], "rowCount": 0,
                "error": f"Translation error: {exc}"}

    try:
        df = sparql_executor.execute(sparql, endpoint)
    except RuntimeError as exc:
        return {"sparql": sparql, "columns": [], "rows": [], "rowCount": 0,
                "error": str(exc).splitlines()[0]}

    columns = list(df.columns)
    rows = [
        {c: (None if v is None else str(v)) for c, v in zip(columns, row)}
        for row in df.itertuples(index=False, name=None)
    ]
    return {"sparql": sparql, "columns": columns, "rows": rows,
            "rowCount": len(rows), "error": None}

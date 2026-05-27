import sys
import os

# Must happen before local imports so ANTHROPIC_API_KEY is set when nl_translator initializes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

import concurrent.futures
import pandas as pd
from mcp.server.fastmcp import FastMCP

import nl_translator
import sparql_executor
import sql_executor
import datasets

mcp = FastMCP("university-query")


def _df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows returned._"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "| " + " | ".join("---" for _ in cols) + " |"
    rows   = [
        "| " + " | ".join(str(v) if v is not None else "" for v in row) + " |"
        for row in df.itertuples(index=False, name=None)
    ]
    return "\n".join([header, sep] + rows)


def _answer(question: str, dataset: str) -> str:
    """Run the NL pipeline for a dataset and format the result as markdown.

    SPARQL runs against the dataset's Ontop endpoint; SQL runs only for datasets
    that support it (university). HR is SPARQL-only.
    """
    cfg = datasets.get(dataset)
    endpoint = cfg["sparql_endpoint"]
    do_sql = "sql" in cfg["languages"]
    start_cmd = "./start_ontop.sh" if dataset == "university" else f"./start_ontop.sh {dataset}"

    try:
        sparql, sql = nl_translator.translate(question, dataset)
    except RuntimeError as exc:
        return f"**Translation error:** {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        sf = pool.submit(sparql_executor.execute, sparql, endpoint)
        qf = pool.submit(sql_executor.execute, sql) if do_sql else None
        try:
            sparql_df, sparql_err = sf.result(), None
        except RuntimeError as exc:
            sparql_df, sparql_err = None, str(exc)
        sql_df = sql_err = None
        if qf is not None:
            try:
                sql_df, sql_err = qf.result(), None
            except RuntimeError as exc:
                sql_df, sql_err = None, str(exc)

    parts = [
        f"## Question · {cfg['label']}\n\n{question}\n",
        f"## Generated SPARQL\n\n```sparql\n{sparql}\n```\n",
    ]
    if do_sql:
        parts.append(f"## Generated SQL\n\n```sql\n{sql}\n```\n")

    if sparql_err:
        tip = f"\n\n> **Tip:** Start Ontop with `{start_cmd}` to enable SPARQL results." \
              if "Cannot connect" in sparql_err else ""
        parts.append(f"## SPARQL Results\n\n> Unavailable: {sparql_err.splitlines()[0]}{tip}\n")
    else:
        n = len(sparql_df)
        parts.append(f"## SPARQL Results\n\n{_df_to_markdown(sparql_df)}\n\n_{n} row{'s' if n != 1 else ''}_\n")

    if do_sql:
        if sql_err:
            parts.append(f"## SQL Results\n\n> Error: {sql_err}\n")
        else:
            n = len(sql_df)
            parts.append(f"## SQL Results\n\n{_df_to_markdown(sql_df)}\n\n_{n} row{'s' if n != 1 else ''}_\n")

    return "\n".join(parts)


@mcp.tool()
def ask_university(question: str) -> str:
    """
    Answer a natural language question about the university dataset.

    Translates the question into SPARQL and SQL using Claude, executes both,
    and returns formatted markdown with the generated queries and results.
    SPARQL requires Ontop running (./start_ontop.sh); SQL always works.

    Examples: "List all students", "Which professors teach more than one course?",
    "Who is enrolled in Database Systems?"
    """
    return _answer(question, "university")


@mcp.tool()
def ask_hr(question: str) -> str:
    """
    Answer a natural language question about the AcmeCorp HR dataset.

    AcmeCorp is a multinational with three subsidiaries (UK, DE, US), each with
    its own local job titles, all mapped via SKOS to a global role catalog and
    anchored to ESCO occupations. Translates the question into SPARQL using
    Claude and runs it against the HR Ontop endpoint (SPARQL-only — there is no
    SQL side for this dataset). Requires the HR endpoint: ./start_ontop.sh hr

    Examples: "Which employees are software engineers across all subsidiaries?",
    "Show the reporting chain for Alice Chen", "Which role mappings need review?",
    "What does AcmeDE call the role AcmeUK calls Senior Software Engineer?"
    """
    return _answer(question, "hr")


@mcp.tool()
def run_sql(query: str) -> str:
    """
    Execute a raw SQL SELECT query against the university DuckDB database.

    Call get_schema() first if you need to know table and column names.
    Example: "SELECT * FROM academic WHERE position = 1"
    """
    try:
        df = sql_executor.execute(query)
    except RuntimeError as exc:
        return f"**SQL error:**\n\n```\n{exc}\n```"
    n = len(df)
    return f"{_df_to_markdown(df)}\n\n_{n} row{'s' if n != 1 else ''}_"


@mcp.tool()
def get_schema() -> str:
    """
    Return the university database schema — tables, columns, types, and position
    code legend — so you can write accurate SQL or ask well-formed questions.
    """
    return """\
## University Database Schema

**student** — s_id INT (PK), fname VARCHAR, lname VARCHAR
**academic** — a_id INT (PK), fname VARCHAR, lname VARCHAR, position INT
  position codes: 1 = Full Professor, 2 = Associate Professor, 3 = Assistant Professor, 9 = PostDoc
**course** — c_id INT (PK), title VARCHAR
**teaching** — a_id INT (FK → academic), c_id INT (FK → course)
**course_registration** — s_id INT (FK → student), c_id INT (FK → course)

Data: 10 students · 6 academics · 5 courses
Courses: Information Systems, Software Engineering, Database Systems, Artificial Intelligence, Computer Networks
"""


@mcp.tool()
def run_sparql_hr(query: str) -> str:
    """
    Execute a raw SPARQL SELECT query against the AcmeCorp HR knowledge graph
    (the Ontop endpoint on port 8081). Call get_hr_schema() first for the
    vocabulary. Requires the HR endpoint: ./start_ontop.sh hr
    """
    try:
        df = sparql_executor.execute(query, datasets.get("hr")["sparql_endpoint"])
    except RuntimeError as exc:
        return f"**SPARQL error:**\n\n```\n{exc}\n```"
    n = len(df)
    return f"{_df_to_markdown(df)}\n\n_{n} row{'s' if n != 1 else ''}_"


@mcp.tool()
def get_hr_schema() -> str:
    """
    Return the AcmeCorp HR ontology reference — prefixes, classes, properties,
    and IRI patterns — so you can write accurate SPARQL or ask well-formed
    questions about the HR knowledge graph.
    """
    return """\
## AcmeCorp HR Ontology (query with SPARQL via ask_hr / run_sparql_hr)

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


if __name__ == "__main__":
    mcp.run()

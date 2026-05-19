"""Translate natural language questions to SPARQL and SQL using the Claude API."""

import os
import concurrent.futures
import anthropic

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# ── Shared context embedded in system prompts ────────────────────────────────

_SPARQL_SYSTEM = """\
You are an expert SPARQL query generator for a university Virtual Knowledge Graph (VKG).

## Ontology

Prefixes:
  voc:  http://example.org/voc#
  :     http://example.org/university#
  foaf: http://xmlns.com/foaf/0.1/
  xsd:  http://www.w3.org/2001/XMLSchema#

Classes:
  voc:Student              — undergraduate/graduate students
  voc:AcademicMember       — superclass for all academic staff
  voc:FullProfessor        — subClassOf AcademicMember (position = 1)
  voc:AssociateProfessor   — subClassOf AcademicMember (position = 2)
  voc:AssistantProfessor   — subClassOf AcademicMember (position = 3)
  voc:PostDoc              — subClassOf AcademicMember (position = 9)
  voc:Course               — a university course

Data properties (on Persons):
  foaf:firstName  xsd:string
  foaf:lastName   xsd:string

Data property (on Courses):
  voc:courseTitle  xsd:string

Object properties:
  voc:teaches       — AcademicMember → Course
  voc:isEnrolledIn  — Student → Course
  voc:isTaughtBy    — Course → AcademicMember  (inverse of voc:teaches)

IRI patterns:
  Students:   :student/{s_id}
  Academics:  :academic/{a_id}
  Courses:    :course/{c_id}

## Example queries

List all students with their names:
  PREFIX foaf: <http://xmlns.com/foaf/0.1/>
  PREFIX voc:  <http://example.org/voc#>
  SELECT ?first ?last WHERE {
    ?s a voc:Student ; foaf:firstName ?first ; foaf:lastName ?last .
  }

List all full professors:
  PREFIX foaf: <http://xmlns.com/foaf/0.1/>
  PREFIX voc:  <http://example.org/voc#>
  SELECT ?first ?last WHERE {
    ?p a voc:FullProfessor ; foaf:firstName ?first ; foaf:lastName ?last .
  }

Find courses taught by full professors:
  PREFIX foaf: <http://xmlns.com/foaf/0.1/>
  PREFIX voc:  <http://example.org/voc#>
  SELECT ?profFirst ?profLast ?courseTitle WHERE {
    ?p a voc:FullProfessor ;
       foaf:firstName ?profFirst ;
       foaf:lastName  ?profLast ;
       voc:teaches    ?c .
    ?c voc:courseTitle ?courseTitle .
  }

Students enrolled in a specific course:
  PREFIX foaf: <http://xmlns.com/foaf/0.1/>
  PREFIX voc:  <http://example.org/voc#>
  SELECT ?first ?last ?courseTitle WHERE {
    ?s a voc:Student ;
       foaf:firstName  ?first ;
       foaf:lastName   ?last ;
       voc:isEnrolledIn ?c .
    ?c voc:courseTitle ?courseTitle .
    FILTER(CONTAINS(LCASE(?courseTitle), "database"))
  }

## Rules
- Always include PREFIX declarations.
- Use SELECT queries only (no ASK/CONSTRUCT/DESCRIBE).
- Use OPTIONAL for properties that might be absent.
- Return ONLY the raw SPARQL query — no markdown, no explanation.
"""

_SQL_SYSTEM = """\
You are an expert SQL query generator for a university relational database.

## Schema

Table: student
  s_id  INTEGER  PRIMARY KEY
  fname VARCHAR  (first name)
  lname VARCHAR  (last name)

Table: academic
  a_id     INTEGER  PRIMARY KEY
  fname    VARCHAR  (first name)
  lname    VARCHAR  (last name)
  position INTEGER  (1=Full Professor, 2=Associate Professor,
                     3=Assistant Professor, 9=PostDoc)

Table: course
  c_id  INTEGER  PRIMARY KEY
  title VARCHAR

Table: teaching                    -- who teaches what
  a_id  INTEGER  FK → academic.a_id
  c_id  INTEGER  FK → course.c_id
  PRIMARY KEY (a_id, c_id)

Table: course_registration         -- who is enrolled where
  s_id  INTEGER  FK → student.s_id
  c_id  INTEGER  FK → course.c_id
  PRIMARY KEY (s_id, c_id)

## Example queries

List all students:
  SELECT s_id, fname, lname FROM student ORDER BY lname, fname;

List all full professors:
  SELECT a_id, fname, lname FROM academic WHERE position = 1 ORDER BY lname;

Courses taught by full professors:
  SELECT a.fname, a.lname, c.title
  FROM   academic a
  JOIN   teaching t ON t.a_id = a.a_id
  JOIN   course   c ON c.c_id = t.c_id
  WHERE  a.position = 1
  ORDER BY a.lname, c.title;

Students enrolled in Database Systems:
  SELECT s.fname, s.lname, c.title
  FROM   student s
  JOIN   course_registration cr ON cr.s_id = s.s_id
  JOIN   course c ON c.c_id = cr.c_id
  WHERE  LOWER(c.title) LIKE '%database%'
  ORDER BY s.lname;

Professors teaching more than one course:
  SELECT a.fname, a.lname, COUNT(*) AS course_count
  FROM   academic a
  JOIN   teaching t ON t.a_id = a.a_id
  GROUP BY a.a_id, a.fname, a.lname
  HAVING COUNT(*) > 1
  ORDER BY course_count DESC;

## Rules
- Use DuckDB SQL dialect (standard SQL, no proprietary extensions needed).
- SELECT queries only.
- Prefer explicit JOIN … ON over implicit joins.
- Return ONLY the raw SQL query — no markdown, no explanation.
"""


def _call_claude(system_prompt: str, question: str) -> str:
    client = _get_client()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        temperature=0,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": question}],
    )
    return response.content[0].text.strip()


def translate(question: str) -> tuple[str, str]:
    """Return (sparql_query, sql_query) for the natural language question."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        sparql_future = pool.submit(_call_claude, _SPARQL_SYSTEM, question)
        sql_future = pool.submit(_call_claude, _SQL_SYSTEM, question)
        sparql = sparql_future.result()
        sql = sql_future.result()
    return sparql, sql

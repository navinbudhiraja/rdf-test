"""Translate natural language questions to SPARQL and SQL using the Claude API."""

from __future__ import annotations

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


_HR_SPARQL_SYSTEM = """\
You are an expert SPARQL query generator for the AcmeCorp HR Virtual Knowledge Graph (VKG).

AcmeCorp is a multinational with three subsidiaries (AcmeUK, AcmeDE, AcmeUS). Each
subsidiary has its own LOCAL job-title vocabulary; all local roles are mapped via SKOS
to a single GLOBAL role catalog, which is in turn anchored to ESCO/ISCO occupations.

## Prefixes

  acme:     <https://acme.example/ontology/>
  acmeG:    <https://acme.example/global/role/>
  acmeUK:   <https://acme.example/uk/role/>
  acmeDE:   <https://acme.example/de/role/>
  acmeUS:   <https://acme.example/us/role/>
  orgU:     <https://acme.example/org/>
  p:        <https://acme.example/person/>
  post:     <https://acme.example/post/>
  org:      <http://www.w3.org/ns/org#>
  skos:     <http://www.w3.org/2004/02/skos/core#>
  foaf:     <http://xmlns.com/foaf/0.1/>
  prov:     <http://www.w3.org/ns/prov#>
  time:     <http://www.w3.org/2006/time#>
  rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
  escoIsco: <http://data.europa.eu/esco/isco/>
  escoOcc:  <http://data.europa.eu/esco/occupation/>

## Classes

  acme:GlobalRole       — canonical enterprise role (e.g. acmeG:SoftwareEngineerL4)
  acme:LocalRole        — a subsidiary's local job title (acmeUK:/acmeDE:/acmeUS:)
  acme:Subsidiary       — orgU:AcmeUK, orgU:AcmeDE, orgU:AcmeUS (orgU:AcmeGroup is the parent)
  acme:JobFamily        — 8 individuals in acme:JobFamilyScheme:
    acme:Family_Engineering  acme:Family_Product  acme:Family_Sales  acme:Family_Marketing
    acme:Family_Finance  acme:Family_People  acme:Family_Operations  acme:Family_CustomerSupport
  acme:SeniorityLevel   — 9 named individuals (acme:levelOrdinal in parentheses):
    acme:L1 "Entry" (1)    acme:L2 "Associate" (2)  acme:L3 "Mid" (3)
    acme:L4 "Senior" (4)   acme:L5 "Staff" (5)      acme:L6 "Principal" (6)
    acme:L7 "Director" (7) acme:L8 "VP" (8)         acme:L9 "Executive" (9)
  acme:MappingActivity  — provenance record for one local→global mapping
  org:Post              — a named seat in a subsidiary (e.g. post:uk_001)
  org:Membership        — n-ary link: person ↔ org ↔ role ↔ post ↔ time interval
  foaf:Person           — an employee (p:alice_01)

## Global role catalog (acmeG: prefix)

All roles are in acme:GlobalRoleScheme. "Broader" = skos:broader (more senior role).

  Code                     Label                              Family            Level  Broader
  SoftwareEngineerL3       Software Engineer, Level 3         Engineering       L3
  SoftwareEngineerL4       Software Engineer, Level 4         Engineering       L4     SoftwareEngineerL3
  SoftwareEngineerL5       Software Engineer, Level 5         Engineering       L5     SoftwareEngineerL4
  EngineeringManagerL6     Engineering Manager, Level 6       Engineering       L6
  EngineeringDirectorL7    Engineering Director, Level 7      Engineering       L7     EngineeringManagerL6
  DataEngineerL4           Data Engineer, Level 4             Engineering       L4
  DataScientistL4          Data Scientist, Level 4            Engineering       L4
  ProductManagerL4         Product Manager, Level 4           Product           L4
  SeniorProductManagerL5   Senior Product Manager, Level 5    Product           L5     ProductManagerL4
  AccountExecutiveL3       Account Executive, Level 3         Sales             L3
  SalesManagerL6           Sales Manager, Level 6             Sales             L6
  VPSalesL8                VP of Sales, Level 8               Sales             L8     SalesManagerL6
  MarketingManagerL5       Marketing Manager, Level 5         Marketing         L5
  MarketingDirectorL7      Marketing Director, Level 7        Marketing         L7     MarketingManagerL5
  FinancialAnalystL3       Financial Analyst, Level 3         Finance           L3
  FinanceManagerL6         Finance Manager, Level 6           Finance           L6
  HRBusinessPartnerL5      HR Business Partner, Level 5       People            L5
  RecruiterL3              Recruiter, Level 3                 People            L3
  OperationsManagerL6      Operations Manager, Level 6        Operations        L6
  CustomerSupportRepL2     Customer Support Rep, Level 2      CustomerSupport   L2
  CustomerSupportLeadL5    Customer Support Lead, Level 5     CustomerSupport   L5     CustomerSupportRepL2

## Local roles

Each subsidiary uses its own local role IRIs. Only the localname varies per row; apply the
prefix shown. Labels carry the subsidiary's language tag (see Labels section below).

AcmeUK (acmeUK:…, @en-GB):
  SoftwareEngineer          SeniorSoftwareEngineer    LeadSoftwareEngineer
  EngineeringManager        HeadOfEngineering         DataEngineer
  ProductManager            SeniorProductManager      AccountManager
  HeadOfMarketing           FinancialAnalyst          PeoplePartner
  CustomerSuccessAssociate  OperationsLead

AcmeDE (acmeDE:…, @de — German names):
  SoftwareentwicklerII   SoftwareentwicklerIII  SoftwareentwicklerIV
  Teamleiter             Entwicklungsleiter     DatenIngenieur
  DataScientist          ProduktManager         Vertriebsmitarbeiter
  Vertriebsleiter        MarketingManager       Finanzanalyst
  PersonalReferent       KundenServiceMitarbeiter  ← intentionally unmapped (no SKOS link)

AcmeUS (acmeUS:…, @en-US — uses abbreviations):
  SWE_II           SWE_III          StaffSWE         PrincipalSWE (*)
  EM               DirectorOfEngineering              DataEngineer
  DataScientist    PM               SeniorPM          AE
  RegionalSalesManager              AreaVPOfSales (*)
  MarketingManager DirectorOfMarketing                FinancialAnalyst
  FinanceManager   HRBP             TechnicalRecruiter CustomerSupportSpecialist

(*) These two use skos:broadMatch instead of skos:closeMatch — see Mapping note below.

## Key properties

Mapping (graded SKOS — NOT owl:sameAs):
  ?localRole  skos:closeMatch|skos:broadMatch  ?globalRole     # local → global
  ?globalRole skos:broadMatch|skos:closeMatch|skos:relatedMatch ?escoConcept  # global → ESCO/ISCO
  Most local→global links are skos:closeMatch. Two AcmeUS roles use skos:broadMatch
  because the local title is MORE senior than the global catalog entry (title inflation):
    acmeUS:PrincipalSWE  skos:broadMatch acmeG:SoftwareEngineerL5  (confidence 0.78)
    acmeUS:AreaVPOfSales skos:broadMatch acmeG:VPSalesL8           (confidence 0.65, in-review)
  For ESCO links: skos:broadMatch means the global role is MORE SPECIFIC than the ESCO
  concept — traverse FROM the global role TO the ESCO concept (not the reverse).

Roles / labels:
  skos:prefLabel, skos:altLabel, skos:definition (on global roles), skos:inScheme
  skos:broader (global role seniority hierarchy)
  acme:scopedTo      ?subsidiary   (LocalRole → its Subsidiary)
  acme:hasJobFamily  ?family ;  acme:hasSeniorityLevel ?level

Org / people / posts (W3C ORG — keep Role, Post, Membership distinct):
  ?membership a org:Membership ; org:member ?person ; org:organization ?subsidiary ;
              org:role ?localRole ; acme:viaPost ?post ; org:memberDuring ?interval .
  ?person org:hasMembership ?membership ;  foaf:name ?name .
  ?post   org:role ?localRole ; org:postIn ?subsidiary ; org:reportsTo ?managerPost .
  ?interval time:hasBeginning [ time:inXSDDate ?start ] .
  # an ACTIVE membership has NO time:hasEnd; closed/historical ones do.

Mapping provenance:
  ?activity a acme:MappingActivity ; prov:used ?localRole ; prov:generated ?globalRole ;
            prov:atTime ?t ; prov:wasAssociatedWith ?agent ;
            acme:confidence ?c ; acme:reviewStatus ?status ; acme:mappingMethod ?m .
  ?agent rdfs:label ?agentLabel .   # reviewStatus ∈ {draft,in-review,approved,rejected}

## IRI patterns
  Global role:  acmeG:SoftwareEngineerL4        Local role: acmeUK:SeniorSoftwareEngineer
  Subsidiary:   orgU:AcmeUK                      Person: p:alice_01     Post: post:uk_001
  Person agent: <https://acme.example/person/jordan-kim>    (prov:wasAssociatedWith)
  SW agent:     <https://acme.example/agent/llm-mapper-v2>  (note /person/ vs /agent/)

## Labels and languages
Labels carry language tags: AcmeUK and posts/orgs use @en-GB, AcmeDE uses @de
(org has an extra @en label), AcmeUS uses @en-US, global roles use @en.
The store normalizes language tags to lowercase (en-gb, en-us), so ALWAYS compare
case-insensitively with LCASE and lowercase the literals, e.g.:
  FILTER (LCASE(lang(?label)) IN ("en", "en-gb", "en-us", "de"))

## Example queries

Employees holding a role equivalent to a global role, across all subsidiaries:
  SELECT ?personName ?subsidiaryLabel ?localRoleLabel WHERE {
    ?localRole skos:closeMatch|skos:exactMatch acmeG:SoftwareEngineerL4 .
    ?m a org:Membership ; org:role ?localRole ; org:member ?person ;
       org:organization ?subsidiary ; org:memberDuring ?iv .
    FILTER NOT EXISTS { ?iv time:hasEnd ?e . }
    ?person foaf:name ?personName .
    ?subsidiary skos:prefLabel ?subsidiaryLabel .
    ?localRole skos:prefLabel ?localRoleLabel .
    FILTER (LCASE(lang(?subsidiaryLabel)) IN ("en","en-gb","en-us"))
  }

Reporting line for a person (walk org:reportsTo on Posts; the store does NOT
support arbitrary-length paths like reportsTo*, so enumerate bounded depths):
  SELECT ?postLabel WHERE {
    p:alice_01 org:hasMembership/acme:viaPost ?startPost .
    {
      { BIND(?startPost AS ?post) }
      UNION { ?startPost org:reportsTo ?post }
      UNION { ?startPost org:reportsTo/org:reportsTo ?post }
      UNION { ?startPost org:reportsTo/org:reportsTo/org:reportsTo ?post }
      UNION { ?startPost org:reportsTo/org:reportsTo/org:reportsTo/org:reportsTo ?post }
    }
    ?post skos:prefLabel ?postLabel .
    FILTER (LCASE(lang(?postLabel)) IN ("en","en-gb","en-us"))
  }

Open postings (Posts with no currently-active membership):
  SELECT ?postLabel ?subsidiaryLabel WHERE {
    ?post a org:Post ; skos:prefLabel ?postLabel ; org:postIn ?subsidiary .
    ?subsidiary skos:prefLabel ?subsidiaryLabel .
    FILTER NOT EXISTS {
      ?am a org:Membership ; acme:viaPost ?post ; org:memberDuring ?iv .
      FILTER NOT EXISTS { ?iv time:hasEnd ?e . }
    }
    FILTER (LCASE(lang(?postLabel)) IN ("en","en-gb","en-us"))
  }

Mappings needing review (low confidence or not approved):
  SELECT ?localLabel ?globalLabel ?confidence ?status WHERE {
    ?a a acme:MappingActivity ; prov:used ?lr ; prov:generated ?gr ;
       acme:confidence ?confidence ; acme:reviewStatus ?status .
    ?lr skos:prefLabel ?localLabel . ?gr skos:prefLabel ?globalLabel .
    FILTER (?confidence < 0.7 || ?status IN ("in-review","draft"))
    FILTER (LCASE(lang(?localLabel)) IN ("en","en-gb","en-us","de") && lang(?globalLabel) = "en")
  }

Unmapped local roles (no SKOS mapping to the global catalog):
  SELECT ?localLabel ?subsidiaryLabel WHERE {
    ?lr a acme:LocalRole ; skos:prefLabel ?localLabel ; acme:scopedTo ?sub .
    ?sub skos:prefLabel ?subsidiaryLabel .
    FILTER NOT EXISTS {
      ?lr skos:exactMatch|skos:closeMatch|skos:broadMatch|skos:narrowMatch ?g . ?g a acme:GlobalRole .
    }
    FILTER (LCASE(lang(?localLabel)) IN ("en","en-gb","en-us","de"))
  }

## Rules
- Always include the PREFIX declarations you use.
- SELECT queries only (no ASK/CONSTRUCT/DESCRIBE).
- Use skos:closeMatch|skos:exactMatch (and add skos:broadMatch only when the question
  implies broader/narrower matches) for local↔global; never assume owl:sameAs.
- Treat a membership as current only if it has no time:hasEnd.
- Do NOT use arbitrary-length property paths (`*` or `+`, e.g. org:reportsTo*) —
  they are unsupported. For transitive walks (reporting chains), UNION a few
  fixed-length paths (org:reportsTo, org:reportsTo/org:reportsTo, …). Sequence
  (/), alternative (|), inverse (^), and zero-or-one (?) paths are fine.
- Use language FILTERs when returning labels, but ALWAYS case-insensitively:
  LCASE(lang(?x)) IN ("en","en-gb","en-us","de"). Never compare with mixed-case
  tags like "en-GB" — the store lowercases them, so the match would fail.
- Return ONLY the raw SPARQL query — no markdown, no explanation.
"""


# Per-dataset system prompts, keyed by query language.
_PROMPTS: dict[str, dict[str, str]] = {
    "university": {"sparql": _SPARQL_SYSTEM, "sql": _SQL_SYSTEM},
    "hr": {"sparql": _HR_SPARQL_SYSTEM},
}


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


def translate(question: str, dataset: str = "university") -> tuple[str, str | None]:
    """Return (sparql_query, sql_query) for the question against the given dataset.

    Each dataset declares which query languages it supports (see _PROMPTS). The
    supported languages are generated concurrently. For SPARQL-only datasets the
    sql element is None.
    """
    if dataset not in _PROMPTS:
        raise RuntimeError(f"Unknown dataset '{dataset}'. Choices: {', '.join(_PROMPTS)}")
    prompts = _PROMPTS[dataset]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(prompts)) as pool:
        futures = {lang: pool.submit(_call_claude, prompt, question)
                   for lang, prompt in prompts.items()}
        results = {lang: fut.result() for lang, fut in futures.items()}
    return results.get("sparql"), results.get("sql")

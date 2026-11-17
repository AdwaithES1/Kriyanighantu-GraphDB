"""Write the synonym graph into Neo4j, and rebuild it from the entries stored there.

  python pipeline/load_neo4j.py      rebuild the graph from the entries (e.g. after changing lexicon.py)

The graph nodes (Verb, Sense, Shade, LookUp, Root) are replaced in one transaction, so readers
never see a half-built graph. The entry nodes (see entries.py) are left alone.
Connection settings come from the environment or .env (see settings.py).
"""
import sys
import time
import uuid
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from settings import connection

LABELS = ["Verb", "Sense", "Shade", "LookUp", "Root"]

STEPS = [
    ("senses", "UNWIND $rows AS r CREATE (:Sense {id:r.id, name:r.name})"),
    ("shades", "UNWIND $rows AS r CREATE (:Shade {id:r.id, gloss:r.gloss, terms:r.terms, glossed:r.glossed})"),
    ("verbs", """UNWIND $rows AS r CREATE (:Verb {id:r.id, headword:r.headword, forms:r.forms,
                 examples:r.examples, in_verb_table:r.in_verb_table})"""),
    ("lookups", """UNWIND $rows AS r CREATE (l:LookUp {id:r.id, label:r.label, english:r.english,
                   reference:r.reference, used_by_verb:r.used_by_verb})
                   WITH l, r UNWIND r.shades AS sid MATCH (s:Shade {id:sid}) CREATE (l)-[:DENOTES]->(s)"""),
    ("roots", "UNWIND $rows AS r CREATE (:Root {id:r.id, text:r.text, gana:r.gana, index:r.index, in_root_table:r.in_root_table})"),
    ("sense_shade", """UNWIND $rows AS r MATCH (a:Sense {id:r[0]}), (b:Shade {id:r[1]})
                       MERGE (a)-[e:HAS_SHADE]->(b)
                       ON CREATE SET e.qualifiers = [] SET e.qualifiers = CASE WHEN r[2] = '' THEN e.qualifiers ELSE e.qualifiers + r[2] END"""),
    ("verb_shade", """UNWIND $rows AS r MATCH (v:Verb {id:r.verb}), (s:Shade {id:r.shade})
                      CREATE (v)-[:HAS_SHADE {id:r.edge_id, sense:r.sense, qualifier:r.qualifier,
                              confidence:r.confidence, sources:r.sources, labels:r.labels, entries:r.entries}]->(s)
                      WITH v, s, r UNWIND r.labels AS label
                      MATCH (l:LookUp {label:label})-[:DENOTES]->(s) MERGE (v)-[:LISTED_UNDER]->(l)"""),
    ("verb_root", """UNWIND $rows AS r MATCH (v:Verb {id:r.verb}), (x:Root {id:r.root})
                     MERGE (v)-[e:FROM_ROOT]->(x) SET e.properties = r.properties, e.it_agama = r.it_agama"""),
    ("see_also", "UNWIND $rows AS r MATCH (a:Verb {id:r[0]}), (b:Verb {id:r[1]}) MERGE (a)-[:SEE_ALSO]->(b)"),
]


def wait_for(driver, seconds):
    """Retry until Neo4j accepts connections (it takes a while to start)."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            driver.verify_connectivity()
            return
        except (ServiceUnavailable, SessionExpired, OSError):
            if time.monotonic() > deadline:
                raise
            print("waiting for Neo4j...", flush=True)
            time.sleep(3)


def load(session, graph):
    """Replace the synonym graph with `graph` atomically and stamp a new version."""
    for label in LABELS:
        session.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
    session.run("CREATE INDEX lookup_label IF NOT EXISTS FOR (n:LookUp) ON (n.label)").consume()
    session.run("CREATE INDEX sense_name IF NOT EXISTS FOR (n:Sense) ON (n.name)").consume()
    session.run("""CREATE FULLTEXT INDEX shade_gloss IF NOT EXISTS FOR (n:Shade) ON EACH [n.gloss]
                   OPTIONS {indexConfig: {`fulltext.analyzer`: 'english'}}""").consume()
    session.run("CALL db.awaitIndexes(120)").consume()

    def write(tx):
        tx.run("MATCH (n) WHERE n:Verb OR n:Sense OR n:Shade OR n:LookUp OR n:Root DETACH DELETE n")
        for key, cypher in STEPS:
            rows = graph[key]
            for start in range(0, len(rows), 500):
                tx.run(cypher, rows=rows[start:start + 500])
        tx.run("MERGE (m:Meta {id: 'graph'}) SET m.version = $version, m.built_at = datetime()",
               version=uuid.uuid4().hex)
    session.execute_write(write)


def graph_version(session):
    record = session.run("MATCH (m:Meta {id: 'graph'}) RETURN m.version AS v").single()
    return record["v"] if record else None


def counts(session):
    return {label: session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"] for label in LABELS}


def main():
    import entries  # here, because entries imports this module
    sys.stdout.reconfigure(encoding="utf-8")
    uri, auth, database = connection()
    with GraphDatabase.driver(uri, auth=auth, notifications_min_severity="OFF") as driver:
        with driver.session(database=database) as session:
            if not entries.count(session):
                raise SystemExit("No entries in the database yet. Run: python pipeline/import_excel.py")
            entries.rebuild_graph(session)
            print("Graph rebuilt:", counts(session))


if __name__ == "__main__":
    main()

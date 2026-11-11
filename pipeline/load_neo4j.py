"""Load output/graph.json into Neo4j, replacing whatever the target database holds.

Connection settings come from the environment or .env (see settings.py).
  python pipeline/load_neo4j.py                      reload everything
  python pipeline/load_neo4j.py --if-empty --wait 180  first start of a server or container
"""
import argparse
import json
import time
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from settings import connection

GRAPH = Path(__file__).resolve().parent.parent / "output" / "graph.json"
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
    """Retry until Neo4j accepts connections (it takes a while to start in a container)."""
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
    session.run("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 2000 ROWS").consume()
    for label in LABELS:
        session.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
    session.run("CREATE INDEX lookup_label IF NOT EXISTS FOR (n:LookUp) ON (n.label)").consume()
    session.run("CREATE INDEX sense_name IF NOT EXISTS FOR (n:Sense) ON (n.name)").consume()
    session.run("""CREATE FULLTEXT INDEX shade_gloss IF NOT EXISTS FOR (n:Shade) ON EACH [n.gloss]
                   OPTIONS {indexConfig: {`fulltext.analyzer`: 'english'}}""").consume()
    session.run("CALL db.awaitIndexes(120)").consume()
    for key, cypher in STEPS:
        rows = graph[key]
        for start in range(0, len(rows), 500):
            session.run(cypher, rows=rows[start:start + 500]).consume()
        print(f"{key}: {len(rows)}")
    for label in LABELS:
        print(label, session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"])
    print("relationships", session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"])


def main():
    parser = argparse.ArgumentParser(description="Load output/graph.json into Neo4j.")
    parser.add_argument("--if-empty", action="store_true", help="do nothing if the graph is already loaded")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="wait this long for Neo4j to start")
    args = parser.parse_args()

    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    uri, auth, database = connection()
    with GraphDatabase.driver(uri, auth=auth) as driver:
        wait_for(driver, args.wait)
        with driver.session(database=database) as session:
            if args.if_empty and session.run("MATCH (v:Verb) RETURN count(v) AS c").single()["c"]:
                print("Graph already loaded; skipping.")
                return
            load(session, graph)


if __name__ == "__main__":
    main()

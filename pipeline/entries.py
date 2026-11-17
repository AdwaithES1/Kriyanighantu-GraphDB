"""The dataset entries, stored in Neo4j. They are the source of truth that replaces the old MongoDB collections.

  (:LookupEntry {lookup, englishMeaning, reference})                       was look_up
  (:RootEntry   {root, ganam, rootIndex})                                  was root_entries
  (:VerbEntry   {verb, lookup, root, ganam, rootIndex, transVerb, ItAgma,
                 derivation, example, reverseWord, seeAlso})               was verb_entries

Every entry also has `id` (stable, used by the portal) and `seq` (its order in the dataset).
All values are kept as text exactly as entered, so the synonym graph built from them is the
same whether they came from the spreadsheets or from the data-entry portal.
"""
import uuid

import build_graph
import load_neo4j

KINDS = {
    "lookup": {
        "label": "LookupEntry",
        "file": "Look-up entry.xlsx",
        "fields": ["lookup", "englishMeaning", "reference"],
        "required": ["lookup", "englishMeaning"],
        "search": ["lookup", "englishMeaning"],
        # spreadsheet column -> field (several spellings are accepted)
        "excel": {"Lookup": "lookup", "LookUp": "lookup", "Look Up": "lookup", "English Meaning": "englishMeaning",
                  "Reference (Bhattamalla) *": "reference", "Reference (Bhattamalla)": "reference",
                  "Reference": "reference"},
    },
    "root": {
        "label": "RootEntry",
        "file": "Root-Entry.xlsx",
        "fields": ["root", "ganam", "rootIndex"],
        "required": ["root", "ganam", "rootIndex"],
        "search": ["root", "ganam"],
        "excel": {"Root": "root", "Ganam": "ganam", "Ganam Index": "rootIndex", "Root Index": "rootIndex"},
    },
    "verb": {
        "label": "VerbEntry",
        "file": "Verb-Entries.xlsx",
        "fields": ["verb", "lookup", "root", "ganam", "rootIndex", "transVerb", "ItAgma", "derivation", "example",
                   "reverseWord", "seeAlso"],
        "required": ["verb", "lookup"],
        "search": ["verb", "lookup", "root"],
        "excel": {"Verb": "verb", "Look Up": "lookup", "Lookup": "lookup", "LookUp": "lookup", "Root": "root",
                  "Ganam": "ganam", "Root Index": "rootIndex", "Properties": "transVerb", "It-Agma": "ItAgma",
                  "Derivation": "derivation", "Example": "example", "Reverse Word": "reverseWord",
                  "See Also": "seeAlso"},
    },
}
MAX_FIELD = 5000


class Invalid(ValueError):
    """The submitted entry cannot be saved; the message says why."""


def ensure_schema(session):
    for kind in KINDS.values():
        label = kind["label"]
        session.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()


def count(session, kind=None):
    labels = [KINDS[kind]["label"]] if kind else [k["label"] for k in KINDS.values()]
    return sum(session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"] for label in labels)


def clean_entry(kind, data):
    """Keep only this kind's fields, as trimmed text; empty becomes None. Raise Invalid if a required one is missing."""
    spec, entry = KINDS[kind], {}
    for field in spec["fields"]:
        value = data.get(field)
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v).strip() for v in value if str(v).strip())
        value = None if value is None else str(value).strip()
        if value and len(value) > MAX_FIELD:
            raise Invalid(f"“{field}” is too long.")
        entry[field] = value or None
    missing = [f for f in spec["required"] if not entry[f]]
    if missing:
        raise Invalid("Required: " + ", ".join(missing) + ".")
    return entry


def public(node):
    return {k: v for k, v in dict(node).items() if k != "seq"}


def fetch_all(session, kind):
    label = KINDS[kind]["label"]
    return [dict(r["n"]) for r in session.run(f"MATCH (n:{label}) RETURN n ORDER BY n.seq")]


def search(session, kind, query="", limit=200):
    """Entries whose main fields contain the query (all entries if it is empty), in dataset order."""
    spec = KINDS[kind]
    where = " OR ".join(f"toLower(coalesce(n.{f}, '')) CONTAINS toLower($q)" for f in spec["search"])
    cypher = (f"MATCH (n:{spec['label']}) WHERE $q = '' OR {where} "
              "WITH n ORDER BY n.seq WITH collect(n) AS found RETURN size(found) AS total, found[..$limit] AS rows")
    record = session.run(cypher, q=query.strip(), limit=limit).single()
    return {"total": record["total"], "entries": [public(n) for n in record["rows"]]}


def get(session, kind, entry_id):
    record = session.run(f"MATCH (n:{KINDS[kind]['label']} {{id: $id}}) RETURN n", id=entry_id).single()
    return public(record["n"]) if record else None


def add(session, kind, data):
    entry, label = clean_entry(kind, data), KINDS[kind]["label"]
    entry["id"] = uuid.uuid4().hex
    session.run(f"OPTIONAL MATCH (m:{label}) WITH coalesce(max(m.seq), 0) + 1 AS seq "
                f"CREATE (n:{label}) SET n = $props, n.seq = seq", props=entry).consume()
    return entry


def update(session, kind, entry_id, data):
    entry = clean_entry(kind, data)  # a None value removes that property
    record = session.run(f"MATCH (n:{KINDS[kind]['label']} {{id: $id}}) SET n += $props RETURN n",
                         id=entry_id, props=entry).single()
    return public(record["n"]) if record else None


def delete(session, kind, entry_id):
    summary = session.run(f"MATCH (n:{KINDS[kind]['label']} {{id: $id}}) DELETE n", id=entry_id).consume()
    return summary.counters.nodes_deleted > 0


def replace_all(session, rows_by_kind):
    """Replace every entry with the given rows ({kind: [dict]}), in one transaction."""
    def write(tx):
        for kind, rows in rows_by_kind.items():
            label = KINDS[kind]["label"]
            tx.run(f"MATCH (n:{label}) DELETE n")
            batch = [dict(row, id=uuid.uuid4().hex, seq=n) for n, row in enumerate(rows, 1)]
            for start in range(0, len(batch), 500):
                tx.run(f"UNWIND $rows AS r CREATE (n:{label}) SET n = r", rows=batch[start:start + 500])
    ensure_schema(session)
    session.execute_write(write)


def rebuild_graph(session):
    """Rebuild the synonym graph (Verb, Sense, Shade, LookUp, Root) from the entries. Returns the build report."""
    frames = build_graph.frames_from_entries(*(fetch_all(session, kind) for kind in ("lookup", "verb", "root")))
    graph, report = build_graph.build(frames, write=False)
    load_neo4j.load(session, graph)
    return report

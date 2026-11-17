"""The plain synonym finder: search by root, verb or meaning, with no context involved.

Search and the field details come from the entry nodes (what the old MongoDB viewer showed).
Synonyms come from the graph: every verb that shares a Shade with the verb, grouped by meaning.
"""
from build_graph import split_forms
from lexicon import clean

LIMIT = 30
MIN_CONFIDENCE = 0.5

SEARCH = {
    "verb": ("VerbEntry", "verb", ["verb"]),
    "root": ("RootEntry", "root", ["root"]),
    "meaning": ("LookupEntry", "lookup", ["lookup", "englishMeaning"]),
}

SYNONYMS = """
MATCH (v:Verb) WHERE any(f IN v.forms WHERE f IN $forms)
MATCH (v)-[r:HAS_SHADE]->(sh:Shade), (se:Sense {id: r.sense})
OPTIONAL MATCH (sh)<-[r2:HAS_SHADE]-(o:Verb) WHERE o <> v AND r2.confidence >= $min
WITH se, sh, r, o, r2 ORDER BY r2.confidence DESC, o.headword
WITH se.name AS meaning, r.qualifier AS qualifier, sh.gloss AS gloss, max(r.confidence) AS confidence,
     [x IN collect(DISTINCT o.headword) WHERE x IS NOT NULL] AS synonyms
RETURN meaning, qualifier, gloss, confidence, synonyms ORDER BY confidence DESC, size(synonyms) DESC
"""
VERBS_OF_MEANING = """
MATCH (l:LookUp {label: $label})-[:DENOTES]->(sh:Shade)<-[r:HAS_SHADE]-(v:Verb) WHERE r.confidence >= $min
RETURN DISTINCT v.headword AS verb ORDER BY verb
"""
RELATED_MEANINGS = """
MATCH (l:LookUp {label: $label})-[:DENOTES]->(:Shade)<-[:DENOTES]-(o:LookUp) WHERE o.label <> $label
RETURN DISTINCT o.label AS lookup, o.english AS englishMeaning ORDER BY lookup LIMIT 50
"""


def entry(node):
    return {k: v for k, v in dict(node).items() if k not in ("seq", "id")}


def search(session, by, query):
    """Entries matching the query: exact first, then prefix, then anywhere."""
    label, key, fields = SEARCH[by]
    query = query.strip()
    if not query:
        return []
    where = " OR ".join(f"toLower(coalesce(n.{f}, '')) CONTAINS toLower($q)" for f in fields)
    cypher = (f"MATCH (n:{label}) WHERE {where} RETURN n ORDER BY "
              f"CASE WHEN n.{key} = $q THEN 0 WHEN n.{key} STARTS WITH $q THEN 1 "
              f"WHEN n.{key} CONTAINS $q THEN 2 ELSE 3 END, n.seq LIMIT $limit")
    return [entry(r["n"]) for r in session.run(cypher, q=query, limit=LIMIT)]


def verb_detail(session, key):
    rows = [dict(r["n"]) for r in session.run("MATCH (n:VerbEntry) WHERE n.verb CONTAINS $k RETURN n ORDER BY n.seq", k=key)]
    exact = [r for r in rows if r["verb"] == key] or [r for r in rows if key in split_forms(r["verb"])]
    if not exact:
        return None
    labels = sorted({r["lookup"] for r in exact if r.get("lookup")})
    lookups = {r["l"]["lookup"]: dict(r["l"]) for r in
               session.run("MATCH (l:LookupEntry) WHERE l.lookup IN $labels RETURN l ORDER BY l.seq DESC", labels=labels)}
    entries = []
    for row in exact:
        item = entry(row)
        meaning = lookups.get(row.get("lookup"), {})
        item["englishMeaning"], item["reference"] = meaning.get("englishMeaning"), meaning.get("reference")
        entries.append(item)
    forms = sorted({form for row in exact for form in split_forms(row["verb"])})
    meanings = [r.data() for r in session.run(SYNONYMS, forms=forms, min=MIN_CONFIDENCE)]
    return {"type": "verb", "title": exact[0]["verb"], "entries": entries, "meanings": meanings}


def root_detail(session, key):
    roots = [entry(r["n"]) for r in session.run("MATCH (n:RootEntry {root: $k}) RETURN n ORDER BY n.seq", k=key)]
    if not roots:
        return None
    verbs = [entry(r["n"]) for r in session.run("MATCH (n:VerbEntry {root: $k}) RETURN n ORDER BY n.seq", k=key)]
    return {"type": "root", "title": key, "entries": roots, "verbs": verbs}


def meaning_detail(session, key):
    lookups = [entry(r["n"]) for r in session.run("MATCH (n:LookupEntry {lookup: $k}) RETURN n ORDER BY n.seq", k=key)]
    if not lookups:
        return None
    listed = [r["verb"] for r in session.run(
        "MATCH (n:VerbEntry {lookup: $k}) RETURN DISTINCT n.verb AS verb, min(n.seq) AS s ORDER BY s", k=key)]
    label = clean(key)
    sharing = [r["verb"] for r in session.run(VERBS_OF_MEANING, label=label, min=MIN_CONFIDENCE)]
    related = [r.data() for r in session.run(RELATED_MEANINGS, label=label)]
    return {"type": "meaning", "title": key, "entries": lookups, "verbs": listed,
            "sharing": [v for v in sharing if v not in listed], "related": related}


DETAIL = {"verb": verb_detail, "root": root_detail, "meaning": meaning_detail}

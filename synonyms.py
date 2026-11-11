"""Context-aware Sanskrit synonym finder over the Kriyanighantu graph.

  python synonyms.py कम्पते
  python synonyms.py कम्पते --context "tremble with fear"
  python synonyms.py कम्पते --context विलसने
  python synonyms.py अकति --broaden
"""
import argparse
import re
import sys
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))
from lexicon import ALIASES, lemma  # noqa: E402
from settings import connection  # noqa: E402

SIBLING_PENALTY = 0.6      # a neighbouring shade of the same sense is a weaker synonym
KEEP_WITHIN = 0.5          # keep shades scoring at least this share of the best match
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

SHADES_OF_VERB = """
MATCH (v:Verb) WHERE $verb IN v.forms
MATCH (v)-[r:HAS_SHADE]->(sh:Shade), (se:Sense {id: r.sense})
RETURN v.id AS verb, v.headword AS headword, sh.id AS shade, sh.gloss AS gloss,
       se.id AS sense, se.name AS sense_name, r.qualifier AS qualifier,
       r.confidence AS confidence, r.labels AS labels
ORDER BY r.confidence DESC, sh.id
"""

CONTEXT_SCORES = """
CALL db.index.fulltext.queryNodes('shade_gloss', $text) YIELD node, score
WHERE node.id IN $shades RETURN node.id AS shade, score
"""

SAME_SHADE = """
MATCH (:Shade {id: $shade})<-[r:HAS_SHADE]-(o:Verb)
WHERE o.id <> $verb AND r.confidence >= $min_confidence
RETURN o.headword AS synonym, o.forms AS forms, r.confidence AS confidence, $shade AS via
"""

SIBLING_SHADES = """
MATCH (:Sense {id: $sense})-[:HAS_SHADE]->(sib:Shade)<-[r:HAS_SHADE]-(o:Verb)
WHERE sib.id <> $shade AND o.id <> $verb AND r.confidence >= $min_confidence
RETURN o.headword AS synonym, o.forms AS forms, r.confidence AS confidence, sib.id AS via
"""


def lucene_query(text):
    """Turn free text into an OR query, escaping nothing by keeping only words."""
    return " OR ".join(re.findall(r"[A-Za-z]{2,}", text))


def select_shades(session, shades, context):
    """Pick the verb's shades the context points at; return (shades, matched?)."""
    if not context:
        return shades, True
    if DEVANAGARI.search(context):
        wanted = {lemma(word) for word in context.split() if word != "च"}
        wanted |= {ALIASES.get(word, word) for word in context.split()}
        hits = [s for s in shades if s["sense_name"] in wanted or context in s["labels"]]
        return (hits, True) if hits else (shades, False)
    query = lucene_query(context)
    ids = [s["shade"] for s in shades]
    scores = {r["shade"]: r["score"] for r in session.run(CONTEXT_SCORES, text=query, shades=ids)} if query else {}
    if not scores:
        return shades, False
    best = max(scores.values())
    return [s for s in shades if scores.get(s["shade"], 0) >= best * KEEP_WITHIN], True


def find(session, verb, context=None, min_confidence=0.5, broaden=False):
    """Return (shades chosen, whether the context matched), each with ranked synonyms."""
    rows = [r.data() for r in session.run(SHADES_OF_VERB, verb=verb)]
    if not rows:
        return [], False
    chosen, matched = select_shades(session, rows, context)
    for shade in chosen:
        shade["synonyms"] = rank_synonyms(session, shade, min_confidence, broaden)
    return chosen, matched


def rank_synonyms(session, shade, min_confidence=0.5, broaden=False):
    """Return [(headword, (score, reason, forms))] for one shade of a verb, best first."""
    args = dict(shade=shade["shade"], verb=shade["verb"], min_confidence=min_confidence)
    ranked = {}
    for rec in session.run(SAME_SHADE, **args):
        ranked[rec["synonym"]] = (round(shade["confidence"] * rec["confidence"], 3), "same shade", rec["forms"])
    if broaden:
        for rec in session.run(SIBLING_SHADES, sense=shade["sense"], **args):
            score = round(shade["confidence"] * rec["confidence"] * SIBLING_PENALTY, 3)
            if rec["synonym"] not in ranked or ranked[rec["synonym"]][0] < score:
                ranked[rec["synonym"]] = (score, f"same sense, shade {rec['via']}", rec["forms"])
    return sorted(ranked.items(), key=lambda kv: (-kv[1][0], kv[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb")
    parser.add_argument("--context", help="English words, or a Sanskrit sense such as विलसने")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--broaden", action="store_true", help="also include other shades of the same sense")
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    uri, auth, database = connection()
    with GraphDatabase.driver(uri, auth=auth) as driver, driver.session(database=database) as session:
        chosen, matched = find(session, args.verb, args.context, args.min_confidence, args.broaden)
    if not chosen:
        print(f"'{args.verb}' has no sense in the graph.")
        return
    if args.context and not matched:
        print(f"Context '{args.context}' matched no sense of this verb; showing all of them.\n")
    for s in chosen:
        qualifier = f" ({s['qualifier']})" if s["qualifier"] else ""
        print(f"[{s['shade']}] {s['sense_name']}{qualifier}  confidence {s['confidence']}")
        print(f"  gloss: {s['gloss'] or '(no English gloss in the dataset)'}")
        for name, (score, why, forms) in s["synonyms"][: args.limit]:
            print(f"  {score:<6} {' / '.join(forms) if len(forms) > 1 else name}   [{why}]")
        extra = len(s["synonyms"]) - args.limit
        print(f"  … {extra} more\n" if extra > 0 else "")


if __name__ == "__main__":
    main()

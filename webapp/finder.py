"""Turns a text and a word into the web app's answer: a best synonym or an explanation.

Two tasks:
  find()          the word is in the text: read its context and give the best synonym from the database.
  find_in_text()  the word need not be in the text: find the words in the text that are its synonyms.
"""
import difflib
import re
from collections import Counter

from text_synonyms import (DEVANAGARI, TOKEN, analyse, find_occurrences, noun_stems, rank_synonyms,
                           sentences, stem_english, synonyms_in_text)

MIN_CONFIDENCE = 0.5
MAX_OCCURRENCES = 10
MAX_ALTERNATIVES = 12
MAX_MATCHES = 20
AFTER_NA = "पफबभमयरलवशषसह"  # the verb sheet ends at न, so these initials are outside it

ROOT_OF_VERB = "MATCH (v:Verb {id: $id})-[:FROM_ROOT]->(r:Root) RETURN r.text AS root LIMIT 1"


def explained(title, message, suggestions=(), in_text=False, label=None):
    """An answer that says why there is no synonym; in_text means suggestions can be retried."""
    return {"status": "explained", "title": title, "message": message, "suggestions": list(suggestions),
            "suggestions_in_text": in_text, "suggestions_label": label}


def close_words(word, pool):
    return difflib.get_close_matches(word, pool, n=5, cutoff=0.7)


def explain_absent_from_text(word, text):
    tokens = sorted(set(TOKEN.findall(text)))
    return explained(f"“{word}” is not in your text",
                     "The word has to appear in the input so its context can be read. "
                     "Check the spelling, or pick one of the similar words from your text.",
                     close_words(word, tokens), in_text=True)


def explain_absent_from_database(lex, word, in_text=True):
    if not DEVANAGARI.search(word):
        start = "The word is in your text, but none" if in_text else "None"
        return explained(f"No Sanskrit verb is glossed as “{word}”",
                         f"{start} of the English meanings in the dataset use it, "
                         "so it cannot be connected to a Sanskrit verb.")
    near = close_words(word, [form for form in lex.by_form if form[0] == word[0]])
    if any(stem in lex.senses_named for stem in noun_stems(word)):
        return explained(f"“{word}” is a meaning word, not a verb",
                         "The database lists synonyms for verbs. This word names a meaning in it, "
                         "so try one of the verbs in your sentence instead.", near)
    if word[0] in AFTER_NA:
        return explained(f"“{word}” is outside this dataset",
                         "The verb list in the dataset only runs from अ to न, so verbs starting with "
                         f"“{word[0]}” are mostly missing. No synonym can be given without inventing one.", near)
    return explained(f"“{word}” is not in the database",
                     "It may be a form the app cannot trace back: only present-tense endings are recognised "
                     "(चलन्ति → चलति), not other tenses, participles or words joined by sandhi. "
                     "It may also simply be absent from the dataset.", near)


def explain_no_meaning(session, verbs, word):
    record = session.run(ROOT_OF_VERB, id=verbs[0]).single()
    root = f" Its root is recorded as “{record['root']}”, but" if record else " But"
    return explained(f"“{word}” has no recorded meaning",
                     f"This verb is in the database.{root} the dataset gives no usable meaning for it, "
                     "so there is nothing to compare it with other verbs on.")


def context_words(lex, result, link):
    """The words from the sentence that actually drove this meaning, as the reader typed them."""
    shade_words = lex.shades[link["shade"]]["words"]
    evidence = result["scores"][link["shade"]][1]
    sanskrit = [token for token, _ in evidence.most_common() if DEVANAGARI.search(token)]
    english = [t for t in re.findall(r"[A-Za-z'-]+", result["sentence"]) if stem_english(t) in shade_words]
    return list(dict.fromkeys(sanskrit + english))[:6]


def ranked_candidates(session, lex, link, target_shades):
    """Synonyms for one meaning, best first, and whether they are exact or only related."""
    rows, kind = rank_synonyms(session, link, MIN_CONFIDENCE), "exact"
    if not rows:
        rows, kind = rank_synonyms(session, link, MIN_CONFIDENCE, broaden=True), "related"

    def key(row):
        name, (score, *_) = row
        links = lex.by_form[name]["links"]
        shared = len({l["shade"] for l in links} & target_shades)
        return (-score, -shared, len(links), name)  # sharing more, and meaning less else, is a purer synonym

    return sorted(rows, key=key), kind


def describe(lex, link, is_english):
    shade = lex.shades[link["shade"]]
    names = shade["senses"] if is_english else [lex.sense_name[link["sense"]]]
    return {"shade": link["shade"], "name": ", ".join(names), "qualifier": link["qualifier"], "gloss": shade["gloss"]}


def as_synonym(row):
    name, (score, _, forms) = row
    return {"word": name, "forms": forms, "score": score}


def build_occurrence(session, lex, result, links, usage, is_english):
    target_shades = {l["shade"] for l in links}
    unique = list({l["shade"]: l for l in links}.values())
    popular = sorted(unique, key=lambda l: (-l["confidence"], -usage[l["shade"]], l["shade"]))
    chosen = list({l["shade"]: l for l in result["chosen"]}.values())
    order = chosen if result["decided"] else popular
    order += [l for l in popular if l["shade"] not in {o["shade"] for o in order}]

    answer, meaning_rows = None, []
    for link in order:
        rows, kind = ranked_candidates(session, lex, link, target_shades)
        entry = describe(lex, link, is_english)
        entry["best"] = as_synonym(rows[0]) if rows else None
        if rows and answer is None:
            answer = {**entry, "kind": kind, "alternatives": [as_synonym(r) for r in rows[1:MAX_ALTERNATIVES + 1]],
                      "because": context_words(lex, result, link), "from_context": link in chosen and result["decided"]}
        else:
            meaning_rows.append(entry)

    if not result["polysemous"]:
        note = "Only one meaning of this word is recorded, so context was not needed."
    elif result["decided"] and answer and answer["from_context"]:
        note = "The surrounding words selected this meaning."
    elif result["decided"]:
        note = "The context pointed to a meaning with no synonyms, so this comes from its next recorded meaning."
    else:
        note = "The surrounding words did not point to one meaning, so this is a best guess from its most attested meaning."
    occurrence = {"sentence": result["sentence"], "token": result["token"], "note": note,
                  "certain": bool(result["decided"] or not result["polysemous"]),
                  "answer": answer, "other_meanings": meaning_rows}
    if answer is None:
        first = describe(lex, order[0], is_english)
        occurrence["explanation"] = {
            "title": "No synonym in the database",
            "message": f"The meaning “{first['name']}” was identified, but no other verb in the dataset shares it, "
                       "even loosely, so no synonym can be given.",
        }
    return occurrence


FIT_NOTES = {
    "single": "This is its only recorded meaning, so it means the same here.",
    "confirmed": "It has other meanings too, but the surrounding words show it is used in this meaning here.",
    "undecided": "It has other meanings too, and the surrounding words do not settle which one is meant here.",
    "other": "The surrounding words suggest it is used in another meaning here ({}), so this is a weaker match.",
}
FIT_RANK = {"confirmed": 0, "single": 0, "undecided": 1, "other": 2}


def describe_match(lex, match):
    link = match["link"]
    meaning = describe(lex, link, False)
    note = FIT_NOTES[match["fit"]].format(", ".join(lex.sense_name[l["sense"]] for l in match["context_choice"]))
    if match["kind"] == "related":
        note = (f"Not an exact synonym: it shares only the broader meaning “{meaning['name']}”, "
                "in a different shade. ") + note
    because = context_words(lex, {"sentence": match["sentence"], "scores": match["scores"]}, link)
    return {"token": match["token"], "headword": match["verb"]["headword"], "sentence": match["sentence"],
            "kind": match["kind"], "fit": match["fit"], "certain": match["fit"] in ("single", "confirmed"),
            "meaning": meaning, "note": note, "because": because}


def explain_no_synonym_in_text(session, lex, word, links, seen):
    names = list(dict.fromkeys(describe(lex, l, not DEVANAGARI.search(word))["name"] for l in links))
    meanings = ", ".join(names[:4]) + (" …" if len(names) > 4 else "")
    if seen:
        listed = ", ".join(seen[:8]) + (" …" if len(seen) > 8 else "")
        message = (f"Your text contains {len(seen)} verb{'s' if len(seen) > 1 else ''} from the dataset ({listed}), "
                   f"but none of them shares a meaning with “{word}” ({meanings}).")
    else:
        message = (f"No verb from the dataset was recognised in your text, so there is nothing to compare “{word}” "
                   "with. Only present-tense forms of verbs from अ to न are recognised.")
    synonyms = []
    for link in sorted(links, key=lambda l: -l["confidence"]):
        synonyms += [name for name, _ in rank_synonyms(session, link, MIN_CONFIDENCE)[:4]]
    return explained(f"No synonym of “{word}” in your text", message, list(dict.fromkeys(synonyms))[:10],
                     label=f"Synonyms of “{word}” in the database, none of which is in your text")


def find_in_text(session, lex, text, word):
    """The word need not be in the text: return the words in the text that are its synonyms."""
    is_english = not DEVANAGARI.search(word)
    links, matches, seen = synonyms_in_text(lex, text, word, MIN_CONFIDENCE)
    if not links:
        verbs = [v["id"] for v in lex.verbs_for(word)[0]] if not is_english else []
        return explain_no_meaning(session, verbs, word) if verbs else explain_absent_from_database(lex, word, in_text=False)
    if not matches:
        return explain_no_synonym_in_text(session, lex, word, links, seen)
    matches.sort(key=lambda m: (FIT_RANK[m["fit"]], m["kind"] != "exact", -m["strength"],
                                -m["scores"][m["link"]["shade"]][0], m["index"]))
    return {"status": "ok", "task": "in_text", "word": word, "meanings": len({l["shade"] for l in links}),
            "matches_total": len(matches), "matches": [describe_match(lex, m) for m in matches[:MAX_MATCHES]]}


def find(session, lex, text, word):
    if not find_occurrences(sentences(text), word):
        return explain_absent_from_text(word, text)
    how, links, results = analyse(lex, text, word)
    is_english = not DEVANAGARI.search(word)
    if not links:
        verbs = [v["id"] for v in lex.verbs_for(word)[0]] if not is_english else []
        return explain_no_meaning(session, verbs, word) if verbs else explain_absent_from_database(lex, word)
    usage = Counter(l["shade"] for v in lex.verbs for l in v["links"])
    return {"status": "ok", "task": "in_context", "word": word, "matched": how, "meanings": len({l["shade"] for l in links}),
            "occurrences_total": len(results),
            "occurrences": [build_occurrence(session, lex, r, links, usage, is_english)
                            for r in results[:MAX_OCCURRENCES]]}

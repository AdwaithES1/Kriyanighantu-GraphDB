"""Turns a text and a word into the web app's answer: a best synonym or an explanation."""
import difflib
import re
from collections import Counter

from text_synonyms import (DEVANAGARI, TOKEN, analyse, find_occurrences, noun_stems, rank_synonyms,
                           sentences, stem_english)

MIN_CONFIDENCE = 0.5
MAX_OCCURRENCES = 10
MAX_ALTERNATIVES = 12
AFTER_NA = "पफबभमयरलवशषसह"  # the verb sheet ends at न, so these initials are outside it

ROOT_OF_VERB = "MATCH (v:Verb {id: $id})-[:FROM_ROOT]->(r:Root) RETURN r.text AS root LIMIT 1"


def explained(title, message, suggestions=(), in_text=False):
    """An answer that says why there is no synonym; in_text means suggestions can be retried."""
    return {"status": "explained", "title": title, "message": message,
            "suggestions": list(suggestions), "suggestions_in_text": in_text}


def close_words(word, pool):
    return difflib.get_close_matches(word, pool, n=5, cutoff=0.7)


def explain_absent_from_text(word, text):
    tokens = sorted(set(TOKEN.findall(text)))
    return explained(f"“{word}” is not in your text",
                     "The word has to appear in the input so its context can be read. "
                     "Check the spelling, or pick one of the similar words from your text.",
                     close_words(word, tokens), in_text=True)


def explain_absent_from_database(lex, word):
    if not DEVANAGARI.search(word):
        return explained(f"No Sanskrit verb is glossed as “{word}”",
                         "The word is in your text, but none of the English meanings in the dataset use it, "
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


def find(session, lex, text, word):
    if not find_occurrences(sentences(text), word):
        return explain_absent_from_text(word, text)
    how, links, results = analyse(lex, text, word)
    is_english = not DEVANAGARI.search(word)
    if not links:
        verbs = [v["id"] for v in lex.verbs_for(word)[0]] if not is_english else []
        return explain_no_meaning(session, verbs, word) if verbs else explain_absent_from_database(lex, word)
    usage = Counter(l["shade"] for v in lex.verbs for l in v["links"])
    return {"status": "ok", "word": word, "matched": how, "meanings": len({l["shade"] for l in links}),
            "occurrences_total": len(results),
            "occurrences": [build_occurrence(session, lex, r, links, usage, is_english)
                            for r in results[:MAX_OCCURRENCES]]}

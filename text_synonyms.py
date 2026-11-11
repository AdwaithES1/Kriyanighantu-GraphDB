"""Find synonyms of a word as it is used in a PDF, a text file or a typed statement.

  python text_synonyms.py passage.pdf --word चलति
  python text_synonyms.py notes.txt --word कम्पते
  python text_synonyms.py "बालकः भयेन कम्पते ।" --word कम्पते

Each occurrence of the word is read in its own context. Words around it are
mapped onto the graph (verbs, sense words, English gloss words) and the shade of
the target verb they agree with most is the meaning used for its synonyms.
"""
import argparse
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))
from lexicon import ALIASES  # noqa: E402
from settings import connection  # noqa: E402
from synonyms import rank_synonyms  # noqa: E402

SAME_SENTENCE, NEIGHBOUR_SENTENCE, REST_OF_TEXT = 1.0, 0.5, 0.1  # weight of context by distance
SENSE_WORD_BONUS = 1.0   # a context word that literally names the sense
MIN_EVIDENCE = 0.08      # below this the context is treated as uninformative
KEEP_WITHIN = 0.7        # also report shades scoring this share of the best
MIN_STEM = 2             # shortest stem accepted when undoing an inflection

STOPWORDS = set("""a an and as at be been by do for from get have in into it of off on or out over
someone somebody something the to up with your yourself about one's""".split())

VERB_ENDINGS = ["न्ति", "न्ते", "न्तु", "ामि", "ामः", "ावः", "ति", "ते", "तु", "सि", "से", "थ"]
# Case endings -> what the Sense stem ends with.
NOUN_ENDINGS = [("ेभ्यः", ""), ("ानाम्", ""), ("ेषु", ""), ("ायाः", "ा"), ("ायाम्", "ा"), ("ायै", "ा"), ("ाभिः", "ा"),
                ("ासु", "ा"), ("ीनाम्", "ि"), ("ेन", ""), ("ाय", ""), ("ात्", ""), ("स्य", ""), ("ैः", ""), ("ाः", ""),
                ("ान्", ""), ("या", "ा"), ("ाम्", "ा"), ("िना", "ि"), ("िम्", "ि"), ("िः", "ि"), ("ेः", "ि"), ("ये", "ि"),
                ("ौ", "ि"), ("ं", ""), ("म्", ""), ("ः", ""), ("े", ""), ("ा", "ा")]

SENTENCE_END = re.compile(r"[।॥.?!\n]+")
TOKEN = re.compile(r"[ऀ-ॣ०-ॿ‌‍]+|[A-Za-z][A-Za-z'-]*")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

LOAD_VERBS = """
MATCH (v:Verb) OPTIONAL MATCH (v)-[r:HAS_SHADE]->(sh:Shade)
WITH v, collect(CASE WHEN sh IS NULL THEN NULL ELSE {shade: sh.id, sense: r.sense, confidence: r.confidence,
     qualifier: r.qualifier} END) AS links
RETURN v.id AS id, v.headword AS headword, v.forms AS forms, links
"""
LOAD_SHADES = """
MATCH (sh:Shade) OPTIONAL MATCH (se:Sense)-[:HAS_SHADE]->(sh)
RETURN sh.id AS id, sh.gloss AS gloss, sh.terms AS terms, collect(se.name) AS senses
"""
LOAD_SENSE_NAMES = "MATCH (s:Sense) RETURN s.id AS id, s.name AS name"


def clean_pdf_text(text):
    """Undo PDF extraction artefacts: doubled vowel signs and hard line wraps."""
    text = re.sub(r"([\u093E-\u094C])\1+", r"\1", text)
    return re.sub(r"\s*\n\s*", " ", text)


def read_file(path):
    """Return the text of a .pdf or UTF-8/UTF-16 text file; raise ValueError if unreadable."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        text = clean_pdf_text(" ".join(page.get_text() for page in pymupdf.open(str(path))))
        if not text.strip():
            raise ValueError("This PDF has no extractable text (it looks scanned). It needs OCR first.")
        return unicodedata.normalize("NFC", text)
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return unicodedata.normalize("NFC", raw.decode(encoding))
        except UnicodeError:
            continue
    raise ValueError("The file is not UTF-8 or UTF-16 text.")


def read_input(source):
    """Command-line input: a file path if one exists, otherwise the statement itself."""
    try:
        is_file = Path(source).is_file()
    except (OSError, ValueError):
        is_file = False
    return read_file(source) if is_file else unicodedata.normalize("NFC", source)


def sentences(text):
    return [tokens for tokens in (TOKEN.findall(s) for s in SENTENCE_END.split(text)) if tokens]


def stem_english(word):
    word = word.lower().strip("'-")
    for suffix in ("ing", "ied", "ies", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def content_words(phrases):
    words = (w for phrase in phrases for w in re.findall(r"[a-z'-]+", phrase.lower()))
    return {stem_english(w) for w in words if w not in STOPWORDS and len(w) > 1}


def verb_stem(token):
    for ending in VERB_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= MIN_STEM:
            return token[: -len(ending)]
    return None


def noun_stems(token):
    if token.endswith("ं"):  # final anusvara is a spelling of म्
        token = token[:-1] + "म्"
    stems = {token}
    for ending, replacement in NOUN_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= MIN_STEM:
            stems.add(token[: -len(ending)] + replacement)
    return stems


class Lexicon:
    """The graph, held in memory for scoring; synonyms are still read from Neo4j."""

    def __init__(self, session):
        self.shades = {r["id"]: r.data() for r in session.run(LOAD_SHADES)}
        self.sense_name = {r["id"]: r["name"] for r in session.run(LOAD_SENSE_NAMES)}
        self.verbs = [r.data() for r in session.run(LOAD_VERBS)]
        self.by_form, self.by_stem, self.senses_named = {}, defaultdict(list), defaultdict(set)
        for verb in self.verbs:
            for form in verb["forms"]:
                self.by_form[form] = verb
                stem = verb_stem(form)
                if stem:
                    self.by_stem[stem].append(verb)
        for shade_id, shade in self.shades.items():
            shade["words"] = content_words(shade["terms"])
            for name in shade["senses"]:
                self.senses_named[name].add(shade_id)
        counts = Counter(w for s in self.shades.values() for w in s["words"])
        total = len(self.shades)
        self.idf = {w: math.log(1 + total / c) for w, c in counts.items()}

    def verbs_for(self, token):
        """Return (verbs, how matched) for a Sanskrit token."""
        if token in self.by_form:
            return [self.by_form[token]], "exact"
        unique = {v["id"]: v for v in self.by_stem.get(verb_stem(token) or "", [])}
        return list(unique.values()), "inflected"

    def gloss_senses(self, verb):
        """One set of gloss words per glossed meaning of the verb."""
        return [self.shades[link["shade"]]["words"] for link in verb["links"] if self.shades[link["shade"]]["words"]]

    def similarity(self, a, b):
        """IDF-weighted cosine between two sets of gloss words."""
        shared = sum(self.idf.get(w, 0) ** 2 for w in a & b)
        if not shared:
            return 0.0
        norm = math.sqrt(sum(self.idf.get(w, 0) ** 2 for w in a) * sum(self.idf.get(w, 0) ** 2 for w in b))
        return shared / norm if norm else 0.0


def context_items(lex, tokens, target_ids, target_words):
    """Map context tokens to graph evidence: [(token, [gloss word sets], sense shades)]."""
    items, english = [], []
    for token in tokens:
        if not DEVANAGARI.search(token):
            word = stem_english(token)
            if token.lower() not in STOPWORDS and word not in target_words:
                english.append(word)
            continue
        verbs, _ = lex.verbs_for(token)
        verbs = [v for v in verbs if v["id"] not in target_ids]
        if verbs:
            meanings = [m for v in verbs for m in lex.gloss_senses(v)]
            if meanings:
                items.append((token, meanings, set()))
            continue
        for stem in map(lambda st: ALIASES.get(st, st), noun_stems(token)):
            if stem in lex.senses_named:
                shade_ids = lex.senses_named[stem]
                items.append((token, [lex.shades[s]["words"] for s in shade_ids], shade_ids))
                break
    if english:
        items.append((" ".join(english), [set(english)], set()))
    return items


def score_shades(lex, shade_ids, weighted_items):
    """Return {shade: (score, {context word: contribution})}."""
    result = {}
    for shade_id in shade_ids:
        words = lex.shades[shade_id]["words"]
        total, evidence = 0.0, Counter()
        for weight, (token, meanings, named) in weighted_items:
            fit = max(lex.similarity(meaning, words) for meaning in meanings)  # its best-fitting meaning
            gain = fit + (SENSE_WORD_BONUS if shade_id in named else 0.0)
            if gain:
                total += weight * gain
                evidence[token] += weight * gain
        result[shade_id] = (total, evidence)
    return result


def find_occurrences(sents, word):
    """Return [(sentence index, token)] where `word` occurs in the text."""
    is_sanskrit = bool(DEVANAGARI.search(word))
    wanted = word if is_sanskrit else stem_english(word)
    hits = []
    for i, tokens in enumerate(sents):
        for token in tokens:
            if (is_sanskrit and wanted in token) or (not is_sanskrit and stem_english(token) == wanted):
                hits.append((i, token))
                break
    return hits


def weighted_context(lex, sents, index, target_ids, target_words):
    items = []
    for i, tokens in enumerate(sents):
        distance = abs(i - index)
        weight = SAME_SENTENCE if distance == 0 else NEIGHBOUR_SENTENCE if distance == 1 else REST_OF_TEXT
        items += [(weight, item) for item in context_items(lex, tokens, target_ids, target_words)]
    return items


def target_links(lex, word):
    """Resolve the input word to [{verb, headword, shade, ...}] and a description."""
    if DEVANAGARI.search(word):
        verbs, how = lex.verbs_for(word)
        links = [dict(link, verb=v["id"], headword=v["headword"]) for v in verbs for link in v["links"]]
        return links, {v["id"] for v in verbs}, how, set()
    wanted = stem_english(word)
    shade_ids = {sid for sid, s in lex.shades.items() if wanted in s["words"]}
    links = [{"verb": "", "headword": word, "shade": sid, "sense": None, "confidence": 1.0, "qualifier": ""}
             for sid in sorted(shade_ids)]
    return links, set(), "English gloss word", {wanted}


def choose(lex, links, scores):
    """Return (links to report, whether the context decided it)."""
    best = max((scores[l["shade"]][0] for l in links), default=0.0)
    if best < MIN_EVIDENCE:
        return links, False
    return [l for l in links if scores[l["shade"]][0] >= best * KEEP_WITHIN], True


def analyse(lex, text, word):
    """Return (how the word matched, per-occurrence analysis) without touching synonyms."""
    sents = sentences(text)
    occurrences = find_occurrences(sents, word)
    if not occurrences:
        raise LookupError(f"'{word}' does not occur in the input text.")
    links, target_ids, how, target_words = target_links(lex, word)
    results = []
    for index, token in occurrences:
        items = weighted_context(lex, sents, index, target_ids, target_words)
        scores = score_shades(lex, {l["shade"] for l in links}, items)
        chosen, decided = choose(lex, links, scores)
        chosen = sorted(chosen, key=lambda l: -scores[l["shade"]][0])
        results.append({"sentence": " ".join(sents[index]), "token": token, "chosen": chosen,
                        "decided": decided, "scores": scores, "polysemous": len({l["shade"] for l in links}) > 1})
    return how, links, results


def print_result(session, lex, result, args, english_query):
    print(f"Sentence: {result['sentence']}")
    if not result["polysemous"]:
        print("Only one meaning of this word is recorded, so context was not needed.")
    elif not result["decided"]:
        print("The context does not point to one meaning; showing every recorded meaning.")
    for link in result["chosen"]:
        shade = lex.shades[link["shade"]]
        score, evidence = result["scores"][link["shade"]]
        names = shade["senses"] if english_query else [lex.sense_name[link["sense"]]]
        qualifier = f" ({link['qualifier']})" if link["qualifier"] else ""
        print(f"\n  Meaning [{link['shade']}] {', '.join(names)}{qualifier}   context score {score:.2f}")
        print(f"  Gloss: {shade['gloss'] or '(no English gloss in the dataset)'}")
        if evidence:
            print("  Because of: " + ", ".join(token for token, _ in evidence.most_common(4)))
        synonyms = rank_synonyms(session, link, args.min_confidence, args.broaden)
        for name, (value, why, forms) in synonyms[: args.limit]:
            print(f"    {value:<6} {' / '.join(forms) if len(forms) > 1 else name}   [{why}]")
        if len(synonyms) > args.limit:
            print(f"    … {len(synonyms) - args.limit} more")
        if not synonyms:
            print("    (no other verb shares this meaning in the database)")
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="path to a .pdf or text file, or the statement itself")
    parser.add_argument("--word", required=True, help="the word in the input to find synonyms for")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--broaden", action="store_true", help="also include other shades of the same sense")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    word = unicodedata.normalize("NFC", args.word.strip())
    try:
        text = read_input(args.input)
    except ValueError as error:
        raise SystemExit(str(error))
    uri, auth, database = connection()
    with GraphDatabase.driver(uri, auth=auth) as driver, driver.session(database=database) as session:
        lex = Lexicon(session)
        try:
            how, links, results = analyse(lex, text, word)
        except LookupError as error:
            hint = " If this is a PDF, its font may not store real Unicode text." if str(args.input).lower().endswith(".pdf") else ""
            raise SystemExit(f"{error}{hint}")
        if not links:
            raise SystemExit(f"'{word}' is in the text, but the database has no meaning recorded for it.")
        print(f"Word: {word}  (matched in database: {how}; {len({l['shade'] for l in links})} recorded meanings)\n")
        for result in results:
            print_result(session, lex, result, args, not DEVANAGARI.search(word))


if __name__ == "__main__":
    main()

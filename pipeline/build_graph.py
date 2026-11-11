"""Build the Verb -> Shade <- Sense graph from the three spreadsheets.

Writes output/graph.json (consumed by load_neo4j.py) and output/report.json.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from lexicon import COMPOUNDS, NOISE_LABELS, QUALIFIED, clean, lemma

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "dataset" / "data"
OUT = ROOT / "output"

ARTHA = r"\(\s*अर्थनि[^)]*\)+"  # the "(अर्थनिर्देशः)" tag, in all its spellings
SEE_SENSE = re.compile(rf"<?\s*([^<>\n]*?)\s*{ARTHA}\s*>?\s*([0-9०-९]+)\s*[.।]\s*([^\n<।.]+)")
SEE_VERB = re.compile(r"<\s*([^<>()]+?)\s*>")
SENSE_ALIAS = re.compile(rf"([^=<>\n]+?)\s*{ARTHA}\s*=\s*<\s*([^<>]+?)\s*{ARTHA}\s*>")
GANA_FIX = {"क्य्रा": "क्र्या", "भ्वा.": "भ्वा", "भ्या": "भ्वा"}
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

NEAR_DUPLICATE = 0.8  # Jaccard at which two glosses of one Sense are the same Shade
WINDOW_MATCH = 0.75   # Jaccard for finding a known gloss inside a longer gloss
VARIANT_SIMILARITY = 0.6  # string similarity at which two forms are one verb

# Confidence of a gloss-to-meaning alignment.
ALIGN_CERTAIN, ALIGN_LIKELY, ALIGN_AMBIGUOUS = 1.0, 0.95, 0.5
# Confidence of a verb-to-sense attestation.
VIA_LOOKUP, VIA_SEE_ALSO, VIA_ROOT = 1.0, 0.9, 0.5
INHERITED_FACTOR = 0.8  # the label has no gloss of its own; it borrows its sense's


def strip_tag(label):
    return clean(re.sub(ARTHA, "", clean(label))).rstrip("( ").strip()


def parse_label(label):
    """Return [(lemma, qualifier)] for a Look Up label, one per atomic meaning."""
    label = strip_tag(label)
    if not label or label in NOISE_LABELS:
        return []
    if label in QUALIFIED:
        return [QUALIFIED[label]]
    quals = re.findall(r"\(([^)]*)\)", label)
    bare = clean(re.sub(r"\([^)]*\)", " ", label))
    if bare in COMPOUNDS:
        tokens = [bare]
    else:
        tokens = [t for piece in bare.split() for t in piece.replace("ऽ", " अ").split()]
    coordinated = (tokens[-1] == "च" or tokens[-1].endswith(("ञ्च", "श्च"))
                   or any(t in COMPOUNDS for t in tokens))
    tokens = [t for t in tokens if t != "च"]
    if not coordinated and len(tokens) > 1:
        # Usually qualifier + head (कुटिलायां गतौ); head-first only with गतौ/गमने.
        if tokens[0] in ("गतौ", "गमने"):
            return [("गति", " ".join(tokens[1:]))]
        return [(lemma(tokens[-1]), " ".join(tokens[:-1]))]
    out = []
    for token in tokens:
        if token in COMPOUNDS:
            out += [(stem, None) for stem in COMPOUNDS[token]]
        elif token in QUALIFIED:
            out.append(QUALIFIED[token])
        else:
            out.append((lemma(token), None))
    if quals and len(out) == 1:  # गतौ (कुत्सायाम्)
        out = [(out[0][0], " ".join(quals))]
    seen, unique = set(), []
    for item in out:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


def split_terms(chunk):
    chunk = re.sub(r"^\s*\(?to[^)]*\)\s*'?", "", chunk.strip())
    terms = (clean(x).strip(" .;'").lower() for x in re.split(r"[,;]", chunk))
    return [t for t in terms if t]


def gloss_blocks(english):
    """Split a gloss on block boundaries: 2+ spaces, newline, or '. ' before a capital."""
    text = re.sub(r"\.\s+(?=[A-Z])", "  ", str(english).strip())
    parts = [p for p in re.split(r"\s*\n\s*|\s{2,}", text) if p.strip()]
    return [t for t in (split_terms(p) for p in parts) if t]


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


class Lookup:
    def __init__(self, label, english, reference):
        self.label = label
        self.english = clean(english)
        self.reference = None if pd.isna(reference) else clean(reference)
        self.comps = parse_label(label)
        self.blocks = gloss_blocks(english)
        self.assign = []  # (meaning indexes, terms, confidence, method)


def known_match(known, comp, runs, own_label):
    """Find the window of `runs` best matching a gloss another lookup attests for `comp`."""
    best = None
    for terms, witnesses in known.get(comp, {}).items():
        if not witnesses - {own_label}:  # a guess must not confirm itself
            continue
        terms, size = list(terms), len(terms)
        for r, run in enumerate(runs):
            for width in range(max(1, size - 2), size + 3):
                for start in range(0, len(run) - width + 1):
                    score = jaccard(terms, run[start:start + width])
                    if score >= WINDOW_MATCH and (best is None or score > best[0]):
                        best = (score, r, start, start + width)
    return best


def align(lookup, known):
    """Assign the gloss of one lookup to its atomic meanings."""
    comps = [c[0] for c in lookup.comps]
    if not comps:
        return []
    if len(comps) == 1:
        return [([0], [t for b in lookup.blocks for t in b], ALIGN_CERTAIN, "direct")]
    runs = [list(b) for b in lookup.blocks]
    result, remaining = [], list(range(len(comps)))
    longest_first = sorted(remaining, key=lambda c: -max([len(t) for t in known.get(comps[c], {})] or [0]))
    for i in longest_first:
        hit = known_match(known, comps[i], runs, lookup.label)
        if hit:
            _, r, a, b = hit
            result.append(([i], runs[r][a:b], ALIGN_CERTAIN, "known_gloss"))
            remaining.remove(i)
            runs = runs[:r] + [x for x in (runs[r][:a], runs[r][b:]) if x] + runs[r + 1:]
    if remaining and runs:
        if len(remaining) == len(runs):
            result += [([i], run, ALIGN_LIKELY, "positional") for i, run in zip(remaining, runs)]
        elif len(remaining) == 1:
            result.append((remaining, [t for run in runs for t in run], ALIGN_LIKELY, "residual"))
        else:
            result += [(list(remaining), run, ALIGN_AMBIGUOUS, "ambiguous") for run in runs]
    return result


def load():
    lookups = pd.read_excel(DATA / "Look-up entry.xlsx", sheet_name="Sheet1", dtype=str)
    verbs = pd.read_excel(DATA / "Verb-Entries.xlsx", dtype=str)
    roots = pd.read_excel(DATA / "Root-Entry.xlsx", dtype=str)
    lookups.columns = ["label", "english", "reference"]
    return lookups.dropna(subset=["label", "english"]), verbs.dropna(subset=["Verb"]), roots


def split_forms(raw):
    forms = re.split(r"\s*[–—/-]\s*|\s*,\s*|\s+अथवा\s+", re.sub(r"[।]", " ", clean(raw)))
    return [f.strip() for f in forms if f.strip()]


def form_clusters(forms):
    """Group the forms of one entry into verbs.

    अञ्चति – अञ्चते are voice/class variants of one verb and merge; प्राणिति – अपानिति
    differ by prefix and are distinct verbs that must stay separate synonyms.
    """
    clusters = []
    for form in forms:
        for cluster in clusters:
            if form[0] == cluster[0][0] and SequenceMatcher(None, form, cluster[0]).ratio() >= VARIANT_SIMILARITY:
                cluster.append(form)
                break
        else:
            clusters.append([form])
    return clusters


def canon_gana(value):
    if pd.isna(value):
        return None
    value = clean(value)
    return GANA_FIX.get(value, value)


def opt(value):
    return None if pd.isna(value) else clean(value)


class Union:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def build():
    lk_df, vb_df, rt_df = load()
    report = Counter()

    # --- Lookups: align composite glosses over several passes, so a gloss
    # learned from one entry can resolve the next.
    lookups = [Lookup(clean(r.label), r.english, r.reference) for r in lk_df.itertuples()]
    by_label = defaultdict(list)
    for n, lk in enumerate(lookups):
        by_label[strip_tag(lk.label)].append(n)
    known = defaultdict(lambda: defaultdict(set))

    def learn(lk):
        for idxs, terms, conf, _ in lk.assign:
            if len(idxs) == 1 and conf >= ALIGN_LIKELY:
                known[lk.comps[idxs[0]][0]][tuple(terms)].add(lk.label)

    for lk in lookups:
        if len(lk.comps) == 1 and lk.comps[0][1] is None:
            lk.assign = align(lk, known)
            learn(lk)
    for _ in range(3):
        for lk in sorted(lookups, key=lambda l: abs(len(l.comps) - len(l.blocks))):
            if len(lk.comps) > 1 or (lk.comps and lk.comps[0][1] is not None):
                lk.assign = align(lk, known)
                if len(lk.comps) > 1:
                    learn(lk)
    for lk in lookups:
        for *_, method in lk.assign:
            report[f"gloss_alignment:{method}"] += 1
        if not lk.comps:
            report["lookup_unparsed"] += 1

    # --- Sense aliases declared by the book in the Reverse Word column.
    alias = {}
    for cell in vb_df["Reverse Word"].dropna():
        for x, y in SENSE_ALIAS.findall(clean(cell)):
            a, b = parse_label(x), parse_label(y)
            if len(a) == 1 and len(b) == 1 and a[0][0] != b[0][0]:
                alias[a[0][0]] = b[0][0]

    def resolve(sense):
        return alias.get(sense, sense)

    report["sense_aliases_from_reverse_word"] = len(alias)

    # --- Shades: one node per distinct term set, near-duplicates merged per Sense.
    shades = {}
    sense_shades = defaultdict(list)  # sense -> [(shade key, qualifier)]

    def get_shade(sense, terms, qualifier):
        key = "|".join(sorted(set(terms)))
        if key not in shades:
            for other, _ in sense_shades[sense]:
                if shades[other]["terms"] and jaccard(shades[other]["terms"], terms) >= NEAR_DUPLICATE:
                    key = other
                    report["near_duplicate_gloss_merged"] += 1
                    break
            else:
                shades[key] = {"terms": sorted(set(terms)), "gloss": ", ".join(terms)}
        if (key, qualifier) not in sense_shades[sense]:
            sense_shades[sense].append((key, qualifier))
        return key

    lookup_links = defaultdict(list)  # lookup index -> [(key, sense, qualifier, conf)]
    for n, lk in enumerate(lookups):
        for idxs, terms, conf, _ in lk.assign:
            if terms:
                for i in idxs:
                    sense, qual = resolve(lk.comps[i][0]), lk.comps[i][1]
                    lookup_links[n].append((get_shade(sense, terms, qual), sense, qual, conf))

    usage = Counter(k for links in lookup_links.values() for k, _, q, _ in links if q is None)

    def default_shade(sense):
        """The shade a bare sense name means: its most attested unqualified gloss."""
        pool = [k for k, q in sense_shades[sense] if q is None] or [k for k, _ in sense_shades[sense]]
        if pool:
            return max(pool, key=lambda k: (usage[k], k))
        key = f"__unglossed__{sense}"
        shades[key] = {"terms": [], "gloss": None}
        sense_shades[sense].append((key, None))
        return key

    # --- Verbs: merge form variants (अञ्चति – अञ्चते) with a union-find.
    uf, form_order, rows = Union(), {}, []

    def register(forms):
        for f in forms:
            form_order.setdefault(f, len(form_order))
            uf.union(forms[0], f)

    for r in vb_df.to_dict("records"):
        for cluster in form_clusters(split_forms(r["Verb"])):
            register(cluster)
            rows.append((r, cluster))

    root_nodes = {}
    for r in rt_df.dropna(subset=["Root"]).to_dict("records"):
        key = (clean(r["Root"]), canon_gana(r["Ganam"]), opt(r["Ganam Index"]))
        root_nodes[key] = {"text": key[0], "gana": key[1], "index": key[2], "in_root_table": True}

    verb_edges, cross_refs, root_edges, lookup_used = {}, set(), {}, set()
    verb_props = defaultdict(lambda: {"forms": set(), "examples": set()})
    table_forms = {f for _, forms in rows for f in forms}
    verb_root_texts = defaultdict(list)

    def link(verb, key, sense, qual, conf, source, label, entry=None):
        rec = verb_edges.setdefault((verb, key), {"confidence": 0.0, "sources": set(), "labels": set(),
                                                  "entries": set(), "sense": sense, "qualifier": qual})
        if conf > rec["confidence"]:
            rec.update(confidence=conf, sense=sense, qualifier=qual)
        rec["sources"].add(source)
        rec["labels"].add(label)
        if entry:
            rec["entries"].add(entry)

    def attach(verb, label, source, base, surface, entry=None):
        """Link a verb to every shade a label denotes; return the number of links."""
        stripped = strip_tag(label)
        indexes = by_label.get(stripped, [])
        if len({lookups[n].english for n in indexes}) > 1:  # अद्भुते: choose by the citation
            cited = [n for n in indexes if lookups[n].reference
                     and any(f in lookups[n].reference for f in surface)]
            indexes = cited or indexes
        made = 0
        for n in indexes:
            lookup_used.add(n)
            for key, sense, qual, conf in lookup_links[n]:
                link(verb, key, sense, qual, min(base, conf), source, stripped, entry)
                made += 1
        if made:
            return made
        for lem, qual in parse_label(stripped):
            sense = resolve(lem)
            link(verb, default_shade(sense), sense, qual, base * INHERITED_FACTOR,
                 source + "+inherited_gloss", stripped, entry)
            made += 1
        return made

    for r, forms in rows:
        vid = uf.find(forms[0])
        verb_props[vid]["forms"].update(forms)
        if pd.notna(r.get("Example")):
            verb_props[vid]["examples"].add(clean(r["Example"]))
        if pd.notna(r["Look Up"]) and not attach(vid, r["Look Up"], "lookup", VIA_LOOKUP, forms):
            report["lookup_label_unusable"] += 1
        if pd.notna(r["Root"]):
            key = (clean(r["Root"]), canon_gana(r["Ganam"]), opt(r["Root Index"]))
            root_nodes.setdefault(key, {"text": key[0], "gana": key[1], "index": key[2], "in_root_table": False})
            root_edges[(vid, key)] = {"properties": opt(r["Properties"]), "it_agama": opt(r["It-Agma"])}
            verb_root_texts[vid].append(key[0])
        if pd.notna(r.get("See Also")):
            see = str(r["See Also"])
            for lab, number, target in SEE_SENSE.findall(see):
                for target_forms in form_clusters(split_forms(target)):
                    register(target_forms)
                    tid = uf.find(target_forms[0])
                    verb_props[tid]["forms"].update(target_forms)
                    attach(tid, lab, "see_also", VIA_SEE_ALSO, target_forms, number.translate(DIGITS))
            for ref in SEE_VERB.findall(SEE_SENSE.sub(" ", see)):
                ref_forms = split_forms(ref)
                if ref_forms and "अर्थनि" not in ref:
                    cross_refs.add((vid, ref_forms[0]))

    # --- Last resort: a verb with no sense takes the meaning its root declares.
    known_senses = set(sense_shades)
    linked = {uf.find(v) for v, _ in verb_edges}
    for vid in {uf.find(v) for v in verb_props} - linked:
        for text in verb_root_texts.get(vid, []):
            parts = text.split(maxsplit=1)
            comps = [c for c in parse_label(parts[1]) if resolve(c[0]) in known_senses] if len(parts) > 1 else []
            for lem, qual in comps:
                sense = resolve(lem)
                link(vid, default_shade(sense), sense, qual, VIA_ROOT, "root_meaning", strip_tag(parts[1]))
            if comps:
                report["verbs_recovered_from_root"] += 1
                break

    # --- Assign ids now that every union is final, then emit.
    groups = defaultdict(lambda: {"forms": set(), "examples": set()})
    for vid, p in verb_props.items():
        g = groups[uf.find(vid)]
        g["forms"] |= p["forms"]
        g["examples"] |= p["examples"]
    order = sorted(groups, key=lambda v: min(form_order[f] for f in groups[v]["forms"]))
    vnum = {v: f"V{i + 1}" for i, v in enumerate(order)}
    report["largest_verb_group"] = max(len(g["forms"]) for g in groups.values())

    sense_names = sorted(sense_shades)
    sid = {s: f"S{i + 1}" for i, s in enumerate(sense_names)}
    shade_id, senses_of = {}, defaultdict(set)
    for s in sense_names:
        n = 0
        for key, _ in sense_shades[s]:
            senses_of[key].add(s)
            if key not in shade_id:
                n += 1
                shade_id[key] = f"{sid[s]}.{n}"

    final_edges = {}
    for (v, key), e in verb_edges.items():
        pair = (uf.find(v), shade_id[key])
        if pair not in final_edges:
            final_edges[pair] = dict(e, sources=set(e["sources"]), labels=set(e["labels"]), entries=set(e["entries"]))
        else:
            cur = final_edges[pair]
            cur["sources"] |= e["sources"]
            cur["labels"] |= e["labels"]
            cur["entries"] |= e["entries"]
            cur["confidence"] = max(cur["confidence"], e["confidence"])

    rid = {k: f"R{i + 1}" for i, k in enumerate(root_nodes)}
    see_also = sorted({(vnum[uf.find(a)], vnum[uf.find(b)]) for a, b in cross_refs
                       if b in form_order and uf.find(b) in vnum and uf.find(a) != uf.find(b)})
    graph = {
        "senses": [{"id": sid[s], "name": s} for s in sense_names],
        "shades": [{"id": shade_id[k], "gloss": v["gloss"], "terms": v["terms"], "glossed": bool(v["terms"])}
                   for k, v in shades.items() if k in shade_id],
        "sense_shade": sorted({(sid[s], shade_id[k], q or "") for s in sense_names for k, q in sense_shades[s]}),
        "verbs": [{"id": vnum[v],
                   "headword": min(groups[v]["forms"], key=lambda f: form_order[f]),
                   "forms": sorted(groups[v]["forms"], key=lambda f: form_order[f]),
                   "examples": sorted(groups[v]["examples"]),
                   "in_verb_table": bool(groups[v]["forms"] & table_forms)} for v in order],
        "verb_shade": [{"verb": vnum[v], "shade": s, "edge_id": f"{vnum[v]}.{s}", "sense": sid[e["sense"]],
                        "qualifier": e["qualifier"] or "", "confidence": round(e["confidence"], 3),
                        "sources": sorted(e["sources"]), "labels": sorted(e["labels"]),
                        "entries": sorted(e["entries"])}
                       for (v, s), e in final_edges.items()],
        "lookups": [{"id": f"L{n + 1}", "label": strip_tag(lk.label), "english": lk.english,
                     "reference": lk.reference, "used_by_verb": n in lookup_used,
                     "shades": sorted({shade_id[k] for k, *_ in lookup_links[n]})}
                    for n, lk in enumerate(lookups)],
        "roots": [{"id": rid[k], **v} for k, v in root_nodes.items()],
        "verb_root": [{"verb": vnum[uf.find(v)], "root": rid[k], **p} for (v, k), p in root_edges.items()],
        "see_also": see_also,
    }
    report.update(
        senses=len(graph["senses"]), shades=len(graph["shades"]), verbs=len(graph["verbs"]),
        verb_shade_edges=len(graph["verb_shade"]),
        verbs_without_shade=len(set(groups) - {v for v, _ in final_edges}),
        shades_unglossed=sum(not s["glossed"] for s in graph["shades"]),
        lookups_unused_by_any_verb=sum(not l["used_by_verb"] for l in graph["lookups"]),
        shades_with_multiple_senses=sum(len(v) > 1 for v in senses_of.values()),
        see_also_verb_refs_unresolved=len(cross_refs) - len(see_also),
    )
    report.update(Counter(f"edge_source:{s}" for e in graph["verb_shade"] for s in e["sources"]))
    OUT.mkdir(exist_ok=True)
    (OUT / "graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(dict(sorted(report.items())), ensure_ascii=False, indent=2), encoding="utf-8")
    return graph, report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    _, rep = build()
    print(json.dumps(dict(sorted(rep.items())), ensure_ascii=False, indent=1))

"""Generate sense-disambiguation test paragraphs from the graph built out of the dataset.

Every target verb is in the database and has synonyms. Each paragraph is written so its
context points to one meaning (`expected`), using only words found in the dataset: the
book's own sense label for that meaning and verbs that have only that meaning. The Sanskrit
is template-made and not grammatical prose; it is test input, not literature.

  python test_data/generate.py      -> test_data/cases.json and test_data/cases/*.txt
"""
import json
import random
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAPH = json.loads((HERE.parent / "output" / "graph.json").read_text(encoding="utf-8"))
random.seed(2026)

SUBJECTS = ["बालकः", "सः", "देवदत्तः", "मुनिः", "नरः", "सा", "शिष्यः", "राजा", "वृक्षः", "जनः"]
FILLERS = ["प्रातः", "ग्रामे", "वने", "नद्याः तीरे", "गृहे", "सायम्", "उद्याने", "नगरे"]

sense_name = {s["id"]: s["name"] for s in GRAPH["senses"]}
shade_gloss = {s["id"]: s["gloss"] for s in GRAPH["shades"]}
verb = {v["id"]: v for v in GRAPH["verbs"]}
links = defaultdict(list)
for e in GRAPH["verb_shade"]:
    links[e["verb"]].append(e)

# Verbs whose only meaning is a given shade: unambiguous context for that shade.
pure = defaultdict(list)
for vid, es in links.items():
    if len(es) == 1 and es[0]["confidence"] >= 0.9 and verb[vid]["in_verb_table"]:
        pure[es[0]["shade"]].append(verb[vid]["headword"])

# A one-word Look Up label that denotes exactly this shade, e.g. क्रीडायाम्.
label_for = {}
for lk in GRAPH["lookups"]:
    if len(lk["shades"]) == 1 and " " not in lk["label"] and "(" not in lk["label"]:
        label_for.setdefault(lk["shades"][0], lk["label"])


def usable(e):
    s = e["shade"]
    return e["confidence"] >= 0.9 and shade_gloss[s] and s in label_for and len(pure[s]) >= 2


candidates = []
for vid, es in links.items():
    good = [e for e in es if usable(e)]
    if len({sense_name[e["sense"]] for e in good}) >= 2 and verb[vid]["in_verb_table"]:
        candidates.append((vid, good))
random.shuffle(candidates)


def context_for(shade, avoid):
    others = [w for w in pure[shade] if w != avoid]
    return label_for[shade], random.sample(others, 2)


def paragraph(target, shade, word=None):
    label, (v1, v2) = context_for(shade, target)
    s1, s2, s3 = random.sample(SUBJECTS, 3)
    place = random.choice(FILLERS)
    return (f"{s1} {place} {v1} । {s2} {label} {word or target} । {s3} अपि {v2} ।"), [label, v1, v2]


def plural(form):
    """चलति -> चलन्ति, only for the plain -अति pattern."""
    return form[:-2] + "न्ति" if re.search(r"[क-ह]ति$", form) else None


def case(n, kind, target, word, text, expected, cues, note=""):
    return {"id": f"T{n:02d}", "kind": kind, "target_verb": target, "word": word, "text": text,
            "expected_meaning": sense_name[expected["sense"]], "expected_shade": expected["shade"],
            "expected_gloss": shade_gloss[expected["shade"]], "context_cues": cues, "note": note}


cases = []
# 1. Same verb, two paragraphs, two meanings (T01-T14).
for vid, good in candidates[:7]:
    target = verb[vid]["headword"]
    a, b = random.sample(good, 2)
    for e in (a, b):
        text, cues = paragraph(target, e["shade"])
        cases.append(case(len(cases) + 1, "pair: same verb, different context", target, target, text, e, cues,
                          f"Paired with the other paragraph for {target}."))

# 2. Both meanings in one paragraph, near and far (T15-T16).
for vid, good in candidates[7:9]:
    target = verb[vid]["headword"]
    near, far = random.sample(good, 2)
    _, far_cues = context_for(far["shade"], target)
    text, cues = paragraph(target, near["shade"])
    text = f"{text} {random.choice(SUBJECTS)} {random.choice(FILLERS)} {far_cues[0]} {far_cues[1]} च ।"
    cases.append(case(len(cases) + 1, "distractor: other meaning's cues one sentence away", target, target, text,
                      near, cues, f"The last sentence carries cues for {sense_name[far['sense']]} instead."))

# 3. Plural form in the text, which must be traced back to the verb (T17-T18).
plural_targets = [(vid, good) for vid, good in candidates[9:] if plural(verb[vid]["headword"])][:2]
for vid, good in plural_targets:
    target = verb[vid]["headword"]
    e = random.choice(good)
    word = plural(target)
    text, cues = paragraph(target, e["shade"], word)
    cases.append(case(len(cases) + 1, "inflected: plural form in the text", target, word, text, e, cues,
                      f"{word} must be matched back to {target}."))

# 4. The same word twice, once in each meaning, in separate sentences (T19-T20).
for vid, good in candidates[12:14]:
    target = verb[vid]["headword"]
    a, b = random.sample(good, 2)
    first, cues_a = paragraph(target, a["shade"])
    second, cues_b = paragraph(target, b["shade"])
    item = case(len(cases) + 1, "two occurrences: one meaning each", target, target, f"{first}\n{second}", a,
                cues_a + cues_b, f"First occurrence expects {sense_name[a['sense']]}, "
                                 f"second expects {sense_name[b['sense']]}.")
    item["expected_per_occurrence"] = [sense_name[a["sense"]], sense_name[b["sense"]]]
    cases.append(item)

out = HERE / "cases"
out.mkdir(exist_ok=True)
for c in cases:
    (out / f"{c['id']}.txt").write_text(c["text"] + "\n", encoding="utf-8")
(HERE / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(cases)} cases from {len(candidates)} candidate verbs")

"""Checks on output/graph.json: the two worked cases in the schema PDF, plus invariants."""
import json
from pathlib import Path

G = json.loads((Path(__file__).resolve().parent.parent / "output" / "graph.json").read_text(encoding="utf-8"))
SENSE = {s["id"]: s["name"] for s in G["senses"]}


def verb(form):
    return next(v for v in G["verbs"] if form in v["forms"])


def edges(form):
    vid = verb(form)["id"]
    return [e for e in G["verb_shade"] if e["verb"] == vid]


def shades(form):
    return {e["shade"] for e in edges(form)}


def senses(form):
    return {SENSE[e["sense"]] for e in edges(form)}


def test_case1_all_verbs_share_the_kutila_shade():
    group = ["अकति", "अटाट्यते", "चञ्चूर्यते", "अगति", "जङ्गम्यते", "अरार्यते"]
    common = set.intersection(*(shades(v) for v in group))
    assert len(common) == 1


def test_case2_composite_lookup_reaches_both_senses():
    assert {"कम्प", "गति"} <= senses("अङ्गति")


def test_case2_kampa_shade_is_shared_across_composites():
    assert shades("चलति") & shades("अङ्गति") & shades("एजति")


def test_case2_vilasana_separates_chalati_from_kampa_only_verbs():
    assert "विलसन" in senses("चलति") and "विलसन" not in senses("एजति")


def test_prefixed_verbs_stay_distinct():
    assert "अपानिति" not in verb("प्राणिति")["forms"]


def test_voice_variants_merge():
    assert "अञ्चते" in verb("अञ्चति")["forms"]


def test_edge_ids_follow_schema_and_are_unique():
    ids = [e["edge_id"] for e in G["verb_shade"]]
    assert len(ids) == len(set(ids))
    assert all(e["edge_id"] == f"{e['verb']}.{e['shade']}" for e in G["verb_shade"])


def test_references_resolve():
    verbs, shade_ids = {v["id"] for v in G["verbs"]}, {s["id"] for s in G["shades"]}
    assert all(e["verb"] in verbs and e["shade"] in shade_ids for e in G["verb_shade"])
    assert len(shade_ids) == len(G["shades"])


def test_confidence_in_range():
    assert all(0 < e["confidence"] <= 1 for e in G["verb_shade"])

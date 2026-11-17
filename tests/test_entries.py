"""The entry store and the Excel import, without the database."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]

import build_graph  # noqa: E402
import entries  # noqa: E402
import import_excel  # noqa: E402

ROWS = {kind: import_excel.read_excel(import_excel.DEFAULT_DIR, kind) for kind in entries.KINDS}


def test_excel_rows_use_the_portal_field_names():
    assert set(ROWS["verb"][0]) == set(entries.KINDS["verb"]["fields"])
    assert set(ROWS["lookup"][0]) == {"lookup", "englishMeaning", "reference"}
    assert set(ROWS["root"][0]) == {"root", "ganam", "rootIndex"}
    assert ROWS["verb"][0]["verb"] == "अकति" and ROWS["verb"][0]["derivation"] is None


def test_graph_from_entries_equals_graph_from_spreadsheets():
    frames = build_graph.frames_from_entries(ROWS["lookup"], ROWS["verb"], ROWS["root"])
    from_entries, _ = build_graph.build(frames, write=False)
    from_excel, _ = build_graph.build(write=False)
    assert json.dumps(from_entries, sort_keys=True) == json.dumps(from_excel, sort_keys=True)


def test_a_new_entry_changes_the_graph():
    extra = ROWS["verb"] + [{"verb": "परीक्षाक्रियति", "lookup": "कम्पे"}]
    graph, _ = build_graph.build(build_graph.frames_from_entries(ROWS["lookup"], extra, ROWS["root"]), write=False)
    assert any("परीक्षाक्रियति" in v["forms"] for v in graph["verbs"])


def test_clean_entry_trims_drops_unknown_fields_and_empties():
    entry = entries.clean_entry("verb", {"verb": "  चलति ", "lookup": "गतौ", "root": "", "hacker": "x", "seeAlso": ["a", " b "]})
    assert entry["verb"] == "चलति" and entry["root"] is None and "hacker" not in entry and entry["seeAlso"] == "a, b"


@pytest.mark.parametrize("kind,data", [("verb", {"verb": "चलति"}), ("lookup", {"lookup": "गतौ", "englishMeaning": " "}),
                                       ("root", {"root": "चल", "ganam": "भ्वादि"})])
def test_clean_entry_requires_the_key_fields(kind, data):
    with pytest.raises(entries.Invalid):
        entries.clean_entry(kind, data)

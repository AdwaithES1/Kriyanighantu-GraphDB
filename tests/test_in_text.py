"""The second finder: a word that need not be in the text, and its synonyms found in the text.

Built from output/graph.json, so the database is not needed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "webapp")]

import finder  # noqa: E402
from text_synonyms import Lexicon, synonyms_in_text  # noqa: E402

LEX = Lexicon.from_graph(json.loads((ROOT / "output" / "graph.json").read_text(encoding="utf-8")))
TREMBLING = "मुनिः नगरे क्ष्मायते । नरः कम्पे केपते । राजा अपि एजति ।"
MOVING = "बालकः नगरे छङ्गयति । जनः गतौ केपते । देवदत्तः अपि चयते ।"


def found(text, word):
    _, matches, _ = synonyms_in_text(LEX, text, word)
    return {m["verb"]["headword"]: (LEX.sense_name[m["link"]["sense"]], m["fit"]) for m in matches}


def test_word_outside_the_text_finds_its_synonyms_inside_it():
    assert "गेपते" not in TREMBLING
    assert set(found(TREMBLING, "गेपते")) == {"क्ष्मायते", "केपते", "एजति"}


def test_shared_meaning_follows_the_context():
    # केपते has both meanings of गेपते; the context decides which one is shared here.
    assert found(TREMBLING, "गेपते")["केपते"] == ("कम्प", "confirmed")
    assert found(MOVING, "गेपते")["केपते"] == ("गति", "confirmed")


def test_english_meaning_word_works_as_query():
    assert "केपते" in found(TREMBLING, "tremble")


def test_the_word_itself_is_not_its_own_synonym():
    assert "केपते" not in found(TREMBLING, "केपते")


def test_no_shared_meaning_gives_no_match_but_lists_verbs_seen():
    _, matches, seen = synonyms_in_text(LEX, "सः गृहे चकति । राजा तृप्तौ तृप्नोति ।", "गेपते")
    assert matches == [] and set(seen) == {"चकति", "तृप्नोति"}


def test_answer_ranks_context_confirmed_matches_first():
    data = finder.find_in_text(None, LEX, TREMBLING, "गेपते")  # the session is only needed for explanations
    assert data["status"] == "ok" and data["matches"][0]["certain"]
    assert all(m["meaning"]["name"] == "कम्प" for m in data["matches"])

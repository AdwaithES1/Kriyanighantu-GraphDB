"""Text handling for text_synonyms.py; none of these need the database."""
from text_synonyms import clean_pdf_text, find_occurrences, noun_stems, read_input, sentences, verb_stem


def test_pdf_cleanup_removes_doubled_vowels_and_wraps():
    assert clean_pdf_text("उद्यााने क्रीीडन्ति\n खेलति") == "उद्याने क्रीडन्ति खेलति"


def test_sentences_split_on_danda_and_period():
    assert len(sentences("सः चलति । सा खेलति॥ He goes. She plays")) == 4


def test_verb_stem_undoes_present_endings():
    assert verb_stem("चलन्ति") == verb_stem("चलति") == "चल"


def test_noun_stems_recover_sense_names():
    assert "भय" in noun_stems("भयेन")
    assert "हिंसा" in noun_stems("हिंसया")
    assert "क्रीडा" in noun_stems("क्रीडायां")


def test_occurrence_found_only_when_present():
    sents = sentences("सः चलति । सा खेलति ।")
    assert [i for i, _ in find_occurrences(sents, "खेलति")] == [1]
    assert find_occurrences(sents, "कम्पते") == []


def test_english_occurrence_ignores_inflection():
    assert find_occurrences(sentences("The bridge was shaking"), "shake")


def test_plain_statement_is_used_as_text():
    assert read_input("सः चलति") == "सः चलति"


def test_utf8_file_is_read(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("सः चलति", encoding="utf-8")
    assert read_input(str(path)) == "सः चलति"

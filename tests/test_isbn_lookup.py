"""
tests/test_isbn_lookup.py
Tests für die reinen Hilfsfunktionen aus isbn_lookup.py - kein Netzwerk-
zugriff, keine Datenbank. Records für den Typ-/Bandnummer-Abgleich werden
als echte (kleine) MARC21-XML-Fragmente konstruiert, wie sie auch real
von der DNB kämen.
"""

import xml.etree.ElementTree as ET

import isbn_lookup


def _record(titel_subfields, publisher=None, isbn=None):
    """Baut ein minimales MARC21-<record>-XML-Element für Tests."""
    df245 = "".join(f'<subfield code="{code}">{text}</subfield>' for code, text in titel_subfields)
    xml = f'<record xmlns="http://www.loc.gov/MARC21/slim"><datafield tag="245">{df245}</datafield>'
    if publisher:
        xml += f'<datafield tag="264"><subfield code="b">{publisher}</subfield></datafield>'
    if isbn:
        xml += f'<datafield tag="020"><subfield code="a">{isbn}</subfield></datafield>'
    xml += "</record>"
    return ET.fromstring(xml)


# ----------------------------------------------------------------- _clean_isbn

def test_clean_isbn_extracts_isbn13_with_extra_text():
    result = isbn_lookup._clean_isbn("978-3-551-12345-6 : EUR 7.50 (Bd. 23)")
    assert result == "9783551123456"


def test_clean_isbn_extracts_isbn13_without_extra_text():
    assert isbn_lookup._clean_isbn("9783551123456") == "9783551123456"


def test_clean_isbn_falls_back_to_isbn10_style():
    result = isbn_lookup._clean_isbn("3-551-12345-X : kart.")
    assert result is not None
    assert "X" in result.upper()


def test_clean_isbn_no_isbn_present_returns_none():
    assert isbn_lookup._clean_isbn("keine ISBN hier") is None


# --------------------------------------------------------------- _band_variants

def test_band_variants_single_digit_includes_leading_zero():
    assert set(isbn_lookup._band_variants(7)) == {"7", "07"}


def test_band_variants_two_digit_no_duplicate():
    assert isbn_lookup._band_variants(23) == ["23"]


def test_band_variants_hundred_and_above_no_padding():
    assert isbn_lookup._band_variants(150) == ["150"]


# ------------------------------------------------------------ _verlag_search_term

def test_verlag_search_term_strips_generic_suffix():
    assert isbn_lookup._verlag_search_term("Carlsen Manga") == "Carlsen"


def test_verlag_search_term_single_word_publisher():
    assert isbn_lookup._verlag_search_term("Egmont") == "Egmont"


def test_verlag_search_term_handles_accented_characters():
    assert isbn_lookup._verlag_search_term("Kazé Manga") == "Kazé"


def test_verlag_search_term_none_input():
    assert isbn_lookup._verlag_search_term(None) is None
    assert isbn_lookup._verlag_search_term("") is None


# ---------------------------------------------------------------- _matches_selection

def test_matches_selection_status_case_insensitive():
    assert isbn_lookup._matches_selection("tba", None, "TBA") is True
    assert isbn_lookup._matches_selection("TBA", None, "tba") is True
    assert isbn_lookup._matches_selection("NA", None, "TBA") is False


def test_matches_selection_month_year():
    assert isbn_lookup._matches_selection("15.09.2026", (9, 2026), None) is True
    assert isbn_lookup._matches_selection("15.10.2026", (9, 2026), None) is False


def test_matches_selection_no_filter_matches_everything():
    assert isbn_lookup._matches_selection("beliebig", None, None) is True


# -------------------------------------------------------------------- _type_matches

def test_type_matches_light_novel_requires_keyword_in_title():
    manga_record = _record([("a", "Konosuba! God's Blessing"), ("n", "11")])
    ln_record = _record([("a", "Konosuba! God's Blessing Light Novel"), ("n", "11")])

    assert isbn_lookup._type_matches(manga_record, "Light Novel") is False
    assert isbn_lookup._type_matches(ln_record, "Light Novel") is True


def test_type_matches_manga_excludes_light_novel_titles():
    manga_record = _record([("a", "Konosuba! God's Blessing"), ("n", "11")])
    ln_record = _record([("a", "Konosuba! God's Blessing Light Novel"), ("n", "11")])

    assert isbn_lookup._type_matches(manga_record, "Manga") is True
    assert isbn_lookup._type_matches(ln_record, "Manga") is False


def test_type_matches_manhwa_no_title_marker_still_matches():
    # Manhwa-Titel haben ueblicherweise KEIN Unterscheidungswort im Titel -
    # das darf nicht faelschlich als Nichtuebereinstimmung gewertet werden
    record = _record([("a", "Irgendein Manhwa-Titel"), ("n", "4")])
    assert isbn_lookup._type_matches(record, "Manhwa") is True


def test_type_matches_unknown_type_never_excludes():
    record = _record([("a", "Beliebiger Titel"), ("n", "1")])
    assert isbn_lookup._type_matches(record, None) is True
    assert isbn_lookup._type_matches(record, "") is True


# --------------------------------------------------------------- _title_matches_band

def test_title_matches_band_with_and_without_leading_zero():
    record_plain = _record([("a", "Testreihe"), ("n", "7")])
    record_padded = _record([("a", "Testreihe"), ("n", "07")])
    assert isbn_lookup._title_matches_band(record_plain, 7) is True
    assert isbn_lookup._title_matches_band(record_padded, 7) is True


def test_title_matches_band_no_false_positive_on_substring():
    # Band 7 darf NICHT in Band 17 "gefunden" werden
    record = _record([("a", "Testreihe"), ("n", "17")])
    assert isbn_lookup._title_matches_band(record, 7) is False
    assert isbn_lookup._title_matches_band(record, 17) is True

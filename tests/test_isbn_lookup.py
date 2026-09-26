"""
tests/test_isbn_lookup.py
Tests für isbn_lookup.py - ohne Netzwerkzugriff. Records für den Typ-/
Bandnummer-Abgleich werden als echte (kleine) MARC21-XML-Fragmente
konstruiert, wie sie auch real von der DNB kämen; SRU-Antworten und
DNB-Anfragen werden per monkeypatch nachgebaut.
"""

import sqlite3
import threading
import xml.etree.ElementTree as ET

import pytest

import changelog
import config
import database as db
import isbn_lookup

MARC_NS = "http://www.loc.gov/MARC21/slim"


def _datafield(tag, subfields):
    inner = "".join(f'<subfield code="{code}">{text}</subfield>' for code, text in subfields)
    return f'<datafield tag="{tag}">{inner}</datafield>'


def _marc_xml(titel_subfields, publisher=None, isbn=None, series=None):
    """MARC21-<record> als XML-Text. `series` = (Reihentitel, Bandangabe) für 490/830."""
    xml = f'<record xmlns="{MARC_NS}">' + _datafield("245", titel_subfields)
    if series:
        xml += _datafield("490", [("a", series[0]), ("v", series[1])])
        xml += _datafield("830", [("a", series[0]), ("v", series[1])])
    if publisher:
        xml += _datafield("264", [("b", publisher)])
    if isbn:
        xml += _datafield("020", [("a", isbn)])
    return xml + "</record>"


def _record(titel_subfields, publisher=None, isbn=None, series=None):
    """Baut ein minimales MARC21-<record>-XML-Element für Tests."""
    return ET.fromstring(_marc_xml(titel_subfields, publisher, isbn, series))


def _sru_response(*marc_records):
    """SRU-Antwort wie von der DNB: jeder MARC-Record steckt in einer
    SRU-Hülle, die ebenfalls <record> heißt."""
    wrapped = "".join(
        f"<record><recordSchema>MARC21-xml</recordSchema><recordData>{m}</recordData></record>"
        for m in marc_records
    )
    return (
        '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
        f"<numberOfRecords>{len(marc_records)}</numberOfRecords><records>{wrapped}</records>"
        "</searchRetrieveResponse>"
    )


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


# ----------------------------------------------------------------- _clean_isbn

def test_clean_isbn_extracts_isbn13_with_extra_text():
    assert isbn_lookup._clean_isbn("978-3-7539-4581-1 : EUR 7.50 (Bd. 15)") == "9783753945811"


def test_clean_isbn_extracts_isbn13_without_extra_text():
    assert isbn_lookup._clean_isbn("9783753945811") == "9783753945811"


def test_clean_isbn_accepts_isbn10_with_x_check_digit():
    assert isbn_lookup._clean_isbn("3-551-12342-X : kart.") == "355112342X"
    assert isbn_lookup._clean_isbn("3-551-12342-x") == "355112342X"


def test_clean_isbn_rejects_wrong_check_digit():
    assert isbn_lookup._clean_isbn("978-3-7539-4581-2 : EUR 7.50") is None   # letzte Ziffer verfälscht
    assert isbn_lookup._clean_isbn("3-551-12345-X") is None


def test_clean_isbn_skips_invalid_number_and_takes_next_valid_one():
    assert isbn_lookup._clean_isbn("1234567890123 9783753945811") == "9783753945811"


def test_clean_isbn_no_isbn_present_returns_none():
    assert isbn_lookup._clean_isbn("keine ISBN hier") is None
    assert isbn_lookup._clean_isbn("") is None


def test_is_valid_isbn_requires_isbn_prefix_for_13_digits():
    assert isbn_lookup._is_valid_isbn("9783759332653") is True
    assert isbn_lookup._is_valid_isbn("4006381333931") is False   # gültige EAN, aber keine ISBN


# ------------------------------------------------------------------- _cql_term

def test_cql_term_quotes_and_removes_special_characters():
    assert isbn_lookup._cql_term("Kaiju No. 8") == '"Kaiju No. 8"'
    assert isbn_lookup._cql_term('Wer ist "Boss"?') == '"Wer ist Boss"'
    assert isbn_lookup._cql_term("A*B^C\\") == '"A B C"'


def test_cql_title_searches_all_words_or_exact_phrase():
    # Gedankenstrich/Doppelpunkt: Wortfolge allein fand bei der DNB nichts
    assert isbn_lookup._cql_title("Nura – Herr der Yokai") == (
        '(tit all "Nura Herr der Yokai" or tit="Nura – Herr der Yokai")'
    )
    assert isbn_lookup._cql_title("NieR:Automata") == '(tit all "NieR Automata" or tit="NieR:Automata")'
    # "Re:Zero" führt die DNB als ein Wort - dafür bleibt die Wortfolge-Suche erhalten
    assert isbn_lookup._cql_title("Re:Zero").endswith(' or tit="Re:Zero")')
    # Sonderzeichen der Suchsprache landen in keinem der beiden Teile
    assert isbn_lookup._cql_title('Wer ist "Boss"?') == '(tit all "Wer ist Boss" or tit="Wer ist Boss")'


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


# ---------------------------------------------------------------------- _band_match

FIELD, TITLE = isbn_lookup.BAND_IN_FIELD, isbn_lookup.BAND_IN_TITLE


def test_band_match_volume_field_with_and_without_leading_zero():
    assert isbn_lookup._band_match(_record([("a", "Testreihe"), ("n", "7")]), 7) == FIELD
    assert isbn_lookup._band_match(_record([("a", "Testreihe"), ("n", "07")]), 7) == FIELD


def test_band_match_no_false_positive_on_substring():
    # Band 7 darf NICHT in Band 17 "gefunden" werden
    record = _record([("a", "Testreihe"), ("n", "17")])
    assert isbn_lookup._band_match(record, 7) == 0
    assert isbn_lookup._band_match(record, 17) == FIELD


def test_band_match_number_in_series_title_is_not_a_volume():
    # "Kaiju No. 8", Band 3: die 8 im Reihentitel ist keine Bandnummer
    with_n = _record([("a", "Kaiju No. 8"), ("n", "3")])
    with_series = _record([("a", "Kaiju No. 8 – Band 3")], series=("Kaiju No.8", "3"))
    for record in (with_n, with_series):
        assert isbn_lookup._band_match(record, 8, "Kaiju No. 8") == 0
        assert isbn_lookup._band_match(record, 3, "Kaiju No. 8") == FIELD
    assert isbn_lookup._band_match(_record([("a", "7 Seeds"), ("n", "2")]), 7, "7 Seeds") == 0


def test_band_match_volume_series_field_490_v():
    record = _record([("a", "Sanda – Band 14")], series=("Sanda", "14"))
    assert isbn_lookup._band_match(record, 14, "Sanda") == FIELD
    assert isbn_lookup._band_match(record, 15, "Sanda") == 0


def test_band_match_falls_back_to_title_text_without_volume_fields():
    # echter DNB-Fall: Band nur im Titel, kein $n/$v
    record = _record([("a", "Konosuba! God's Blessing On This Wonderful World! Light Novel 10")])
    assert isbn_lookup._band_match(record, 10, "Konosuba!") == TITLE
    assert isbn_lookup._band_match(record, 1, "Konosuba!") == 0


def test_band_match_title_text_needs_number_beyond_series_title():
    only_title = _record([("a", "Kaiju No. 8")])
    band_eight = _record([("a", "Kaiju No. 8 Band 8")])
    assert isbn_lookup._band_match(only_title, 8, "Kaiju No. 8") == 0
    assert isbn_lookup._band_match(band_eight, 8, "Kaiju No. 8") == TITLE


# ------------------------------------------------------ _run_dnb_query / Anfrage

@pytest.fixture
def fake_dnb(monkeypatch):
    """Ersetzt requests.get; gibt nacheinander die in `responses` abgelegten
    Antworten zurück und merkt sich die abgesetzten Anfragen."""
    state = {"responses": [], "queries": []}

    def fake_get(url, params, timeout):
        state["queries"].append(params["query"])
        return _FakeResponse(state["responses"].pop(0))

    monkeypatch.setattr(isbn_lookup.requests, "get", fake_get)
    monkeypatch.setattr(isbn_lookup, "REQUEST_DELAY_SECONDS", 0)
    return state


def test_query_uses_publisher_index_and_escapes_title(fake_dnb):
    fake_dnb["responses"] = [_sru_response(), _sru_response()]
    isbn_lookup.lookup_isbn_dnb('Wer ist "Boss"?', 3, verlag="Carlsen Manga")
    with_publisher, fallback = fake_dnb["queries"]
    title_clause = '(tit all "Wer ist Boss" or tit="Wer ist Boss")'
    assert with_publisher.startswith(f"{title_clause} and mat=books")
    assert with_publisher.endswith('and vlg="Carlsen"')
    assert "WOE" not in with_publisher
    assert fallback.startswith(f"{title_clause} and mat=books") and "vlg" not in fallback


def test_special_edition_listed_first_is_not_chosen_but_returned_separately(fake_dnb):
    schuber = _marc_xml([("a", "Dandadan – Band 20 mit Sammelschuber")], "Crunchyroll Manga", "9783755507260")
    regular = _marc_xml([("a", "Dandadan – Band 20")], "Crunchyroll Manga", "9783753945811", series=("Dandadan", "20"))
    fake_dnb["responses"] = [_sru_response(schuber, regular)]
    log = []

    isbn, confidence, specials = isbn_lookup.lookup_isbn_dnb("Dandadan", 20, verlag="Crunchyroll", log=log)

    assert (isbn, confidence) == ("9783753945811", "band+verlag")
    assert specials == [isbn_lookup.Sonderausgabe("9783755507260", "Dandadan – Band 20 mit Sammelschuber")]
    # SRU-Hüllen zählen nicht als eigene Records
    assert any("2 Records gesamt, 2 mit Band 20 (1 im Bandfeld, 1 nur im Titeltext, 1 Sonderausgaben)" in line
               for line in log)


def test_title_text_only_match_is_marked_uncertain(fake_dnb):
    ln10 = _marc_xml([("a", "Konosuba! God's Blessing On This Wonderful World! Light Novel 10")],
                     "TOKYOPOP GmbH", "9783759332653")
    fake_dnb["responses"] = [_sru_response(ln10)]
    assert isbn_lookup.lookup_isbn_dnb("Konosuba!", 10, verlag="Tokyopop", typ="Light Novel") == (
        "9783759332653", "titeltext", []
    )


def test_record_with_invalid_isbn_is_skipped(fake_dnb):
    broken = _marc_xml([("a", "Sanda")], "Pegasus", "978-3-7539-4581-2", series=("Sanda", "14"))
    fine = _marc_xml([("a", "Sanda")], "Pegasus", "9783759314086", series=("Sanda", "14"))
    fake_dnb["responses"] = [_sru_response(broken, fine)]
    assert isbn_lookup.lookup_isbn_dnb("Sanda", 14, verlag="Pegasus")[0] == "9783759314086"


def test_sru_diagnostic_is_logged_instead_of_silently_finding_nothing(fake_dnb):
    fake_dnb["responses"] = [
        '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><diagnostics>'
        '<diagnostic xmlns="http://www.loc.gov/zing/srw/diagnostic/"><uri>info:srw/diagnostic/1/10</uri>'
        "<message>Query syntax error</message><details>expected index or term</details></diagnostic>"
        "</diagnostics></searchRetrieveResponse>"
    ]
    log = []
    assert isbn_lookup.lookup_isbn_dnb("Titel", 1, log=log) == (None, "keine", [])
    assert any("Query syntax error - expected index or term" in line for line in log)


# ------------------------------------------------- fill_missing_isbns & Bestellliste

@pytest.fixture
def lookup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "manga_library.db")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(changelog, "LOG_DIR", tmp_path / "LOG")      # Logdateien in tmp_path/LOG
    monkeypatch.setattr(isbn_lookup, "REQUEST_DELAY_SECONDS", 0)
    db.init_db()
    db.replace_all([
        {"titel": "Alpha", "baende_bis": "1", "voe_1": "TBA"},
        {"titel": "Beta", "baende_bis": "2", "voe_1": "TBA"},
        {"titel": "Gamma", "baende_bis": "3", "voe_1": "TBA"},
    ])
    return str(db.DB_FILE)


def _cached(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT titel, isbn FROM isbn_cache"))
    finally:
        conn.close()


def test_found_isbn_is_saved_immediately(lookup_db, monkeypatch):
    def lookup(titel, band, verlag, typ, log):
        if titel == "Beta":
            raise RuntimeError("Absturz mitten im Abgleich")
        return "9783753945811", "dnb (band+verlag)", []

    monkeypatch.setattr(isbn_lookup, "lookup_isbn", lookup)
    with pytest.raises(RuntimeError):
        isbn_lookup.fill_missing_isbns(lookup_db, only_status="TBA")
    assert _cached(lookup_db) == {"Alpha": "9783753945811"}   # Treffer vor dem Absturz ist gespeichert


def test_progress_is_reported_and_cancel_stops_after_current_title(lookup_db, monkeypatch):
    cancel = threading.Event()
    seen = []

    def lookup(titel, band, verlag, typ, log):
        cancel.set()   # Nutzer klickt während des ersten Titels auf "Abbrechen"
        return "9783753945811", "dnb (band+verlag)", []

    monkeypatch.setattr(isbn_lookup, "lookup_isbn", lookup)
    report = isbn_lookup.fill_missing_isbns(
        lookup_db, only_status="TBA", progress=lambda *args: seen.append(args), cancel=cancel,
    )

    assert seen == [(0, 3, "Alpha")]
    assert report.abgebrochen and report.gesamt == 3
    assert [r.titel for r in report.gefunden] == ["Alpha"]
    assert _cached(lookup_db) == {"Alpha": "9783753945811"}
    assert "ABGEBROCHEN: nur 1 von 3 Titeln geprüft" in report.summary()


def test_summary_lists_uncertain_hits_with_reason():
    report = isbn_lookup.LookupReport(gefunden=[
        isbn_lookup.LookupResult(1, "Sicher", "V", 2, "1", "dnb (band+verlag)"),
        isbn_lookup.LookupResult(2, "OhneVerlag", "V", 3, "2", "dnb (band_only)"),
        isbn_lookup.LookupResult(3, "NurTitel", "V", 4, "3", "dnb (titeltext)"),
    ])
    text = report.summary()
    assert "davon sicher (DNB, Bandfeld + Verlag): 1" in text
    assert "OhneVerlag Band 3 (V) → ISBN 2 [Verlag nicht bestätigt]" in text
    assert "NurTitel Band 4 (V) → ISBN 3 [Band nur im Titel erkannt]" in text
    assert "Sicher Band" not in text.split("prüfen:")[1]


def test_bestellliste_is_sorted_by_date_not_by_text(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "manga_library.db")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    db.init_db()
    db.replace_all([
        {"titel": "Spät", "baende_bis": "1", "voe_1": "15.09.2026"},
        {"titel": "Früh", "baende_bis": "1", "voe_1": "5.09.2026"},
        {"titel": "Monat", "baende_bis": "1", "voe_1": "09.2026"},   # MM.JJJJ = Monatsanfang
    ])
    liste = isbn_lookup.bestellliste_markdown(str(db.DB_FILE), 9, 2026)
    order = [line.split("|")[2].strip() for line in liste.splitlines() if line.startswith("| ") and "Titel" not in line]
    assert order == ["Monat", "Früh", "Spät"]


# ------------------------------------------------------------------ Sonderausgaben

@pytest.mark.parametrize("titel_a, series_title, edition", [
    # echte DNB-Titel
    ("Blue Lock – Band 33 – Collector's Edition", "Blue Lock", None),
    ("Colette beschließt zu sterben Collectors Edition 20", "Colette beschließt zu sterben", None),
    ("Dandadan – Band 20 mit Sammelschuber", "Dandadan", None),
    ("Dandadan – Band 16-20 im Sammelschuber", "Dandadan", None),
    ("GACHIAKUTA 15 im Schuber", "Gachiakuta", None),
    ("Die Braut des Magiers 21 - Limited Edition", "Die Braut des Magiers", None),
    ("Strange Pictures - Seltsame Bilder 01 Variant", "Strange Pictures - Seltsame Bilder", None),
    ("Berserk Max 21 - Tarot-Edition", "Berserk Max", None),
    ("Blue Lock – Band 29 – mit Acryl-Aufsteller", "Blue Lock", None),
    ("KINGDOM Starter Pack", "Kingdom", None),
    ("Bad Boy Yagami 2in1 05 + Box", "Bad Boy Yagami", None),
    ("Naruto Massiv 5", "Naruto", None),
    ("Conni im Ferienlager", "Conni", "Sonderausgabe"),
])
def test_special_editions_are_recognized(titel_a, series_title, edition):
    xml = f'<record xmlns="{MARC_NS}">' + _datafield("245", [("a", titel_a)])
    if edition:
        xml += _datafield("250", [("a", edition)])
    record = ET.fromstring(xml + "</record>")
    assert isbn_lookup._special_edition(record, series_title) is not None


@pytest.mark.parametrize("titel_a, series_title, edition", [
    ("Blue Lock – Band 33", "Blue Lock", "1. Auflage"),
    ("Sakamoto Days 25", "Sakamoto Days", None),
    # Beigabe der normalen Erstauflage ist keine Sonderausgabe
    ("Cat's Eye - Ein Supertrio 02", "Cat's Eye", "Mit Collector's Print als Extra in der 1.Auflage!"),
    # Begriff steckt schon im Reihentitel
    ("Blue Box 17", "Blue Box", None),
    ("NARUTO Massiv 5", "NARUTO Massiv", None),
    ("Sailor Moon - Neuedition 3", "Sailor Moon", None),
])
def test_normal_editions_are_not_flagged(titel_a, series_title, edition):
    xml = f'<record xmlns="{MARC_NS}">' + _datafield("245", [("a", titel_a)])
    if edition:
        xml += _datafield("250", [("a", edition)])
    record = ET.fromstring(xml + "</record>")
    assert isbn_lookup._special_edition(record, series_title) is None


def test_special_edition_label_strips_sort_markers_and_names_edition_field():
    record = ET.fromstring(
        f'<record xmlns="{MARC_NS}">' + _datafield("245", [("a", "\x98Die\x9c Braut des Magiers 21 - Limited Edition")])
        + "</record>"
    )
    assert isbn_lookup._special_edition(record, "Die Braut des Magiers") == "Die Braut des Magiers 21 - Limited Edition"
    record = ET.fromstring(
        f'<record xmlns="{MARC_NS}">' + _datafield("245", [("a", "Absolute Batman")])
        + _datafield("250", [("a", "Deluxe Edition")]) + "</record>"
    )
    assert isbn_lookup._special_edition(record, "Absolute Batman") == "Absolute Batman (Deluxe Edition)"


def test_only_special_edition_found_gives_no_isbn_but_lists_it(fake_dnb):
    collector = _marc_xml([("a", "Blue Lock – Band 33 – Collector's Edition")], "Pegasus Manga", "9783759314086",
                          series=("Blue Lock", "33"))
    # beide Anfragen (mit Verlag, dann ohne) finden nur die Sonderausgabe
    fake_dnb["responses"] = [_sru_response(collector), _sru_response(collector)]

    isbn, confidence, specials = isbn_lookup.lookup_isbn_dnb("Blue Lock", 33, verlag="Pegasus")

    assert (isbn, confidence) == (None, "keine")
    assert [s.isbn for s in specials] == ["9783759314086"]              # nicht doppelt aus beiden Anfragen
    assert len(fake_dnb["queries"]) == 2                                # normale Ausgabe auch ohne Verlag gesucht


def test_special_edition_of_other_publisher_is_ignored(fake_dnb):
    regular = _marc_xml([("a", "Sanda – Band 14")], "Pegasus Manga", "9783753945811", series=("Sanda", "14"))
    other = _marc_xml([("a", "Sanda – Band 14 – Limited Edition")], "Anderer Verlag", "9783759314086",
                      series=("Sanda", "14"))
    fake_dnb["responses"] = [_sru_response(regular, other)]
    assert isbn_lookup.lookup_isbn_dnb("Sanda", 14, verlag="Pegasus") == ("9783753945811", "band+verlag", [])


def _specials_in_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return sorted(conn.execute("SELECT titel, isbn, bezeichnung FROM isbn_sonderausgaben"))
    finally:
        conn.close()


def test_normal_edition_goes_to_cache_special_editions_to_own_table(lookup_db, monkeypatch):
    results = {
        "Alpha": ("9783753945811", "dnb (band+verlag)",
                  [isbn_lookup.Sonderausgabe("9783759314086", "Alpha 2 Limited")]),
        "Beta": (None, "keine", [isbn_lookup.Sonderausgabe("9783759332653", "Beta 3 im Schuber")]),
        "Gamma": ("9783551795274", "dnb (band+verlag)", []),
    }
    monkeypatch.setattr(isbn_lookup, "lookup_isbn", lambda titel, *args, **kw: results[titel])

    report = isbn_lookup.fill_missing_isbns(lookup_db, only_status="TBA")

    assert _cached(lookup_db) == {"Alpha": "9783753945811", "Gamma": "9783551795274"}   # nur normale Ausgaben
    assert _specials_in_db(lookup_db) == [
        ("Alpha", "9783759314086", "Alpha 2 Limited"), ("Beta", "9783759332653", "Beta 3 im Schuber"),
    ]
    text = report.summary()
    assert f"{isbn_lookup.SONDERAUSGABE_MARKER} Alpha Band 2: normale Ausgabe ISBN 9783753945811" in text
    assert "  - Beta Band 3: keine normale Ausgabe gefunden" in text

    # erneute Suche ersetzt die Sonderausgaben dieses Band-Stands
    results["Beta"] = (None, "keine", [])
    isbn_lookup.fill_missing_isbns(lookup_db, only_status="TBA")   # Alpha/Gamma sind im Cache -> nur Beta
    assert _specials_in_db(lookup_db) == [("Alpha", "9783759314086", "Alpha 2 Limited")]


def test_bestellliste_shows_special_editions_and_marks_band_with_both(lookup_db, monkeypatch):
    results = {
        "Alpha": ("9783753945811", "dnb (band+verlag)",
                  [isbn_lookup.Sonderausgabe("9783759314086", "Alpha | 2 Limited")]),
        "Beta": (None, "keine", [isbn_lookup.Sonderausgabe("9783759332653", "Beta 3 im Schuber")]),
        "Gamma": ("9783551795274", "dnb (band+verlag)", []),
    }
    monkeypatch.setattr(isbn_lookup, "lookup_isbn", lambda titel, *args, **kw: results[titel])
    isbn_lookup.fill_missing_isbns(lookup_db, only_status="TBA")

    rows = [line for line in isbn_lookup.bestellliste_markdown(lookup_db, status="TBA").splitlines()
            if line.startswith("| TBA")]
    star = isbn_lookup.SONDERAUSGABE_MARKER
    assert rows[0].startswith(f"| TBA | {star} Alpha |") and "9783753945811" in rows[0]
    assert rows[1].startswith(f"| TBA | {star} ↳ Sonderausgabe: Alpha / 2 Limited |") and "9783759314086" in rows[1]
    # nur Sonderausgabe: normale Zeile mit Fallback-Link, nichts golden
    assert rows[2].startswith("| TBA | Beta |") and "buchhandel.de" in rows[2]
    assert rows[3].startswith("| TBA | ↳ Sonderausgabe: Beta 3 im Schuber |") and "9783759332653" in rows[3]
    assert rows[4].startswith("| TBA | Gamma |") and star not in rows[4]
    assert all(line.count("|") == 7 for line in rows)                   # "|" in der Bezeichnung zerschneidet nichts


def test_special_editions_are_kept_if_entered_publisher_is_not_among_results(fake_dnb):
    # eingetragener Verlag ist veraltet: normale Ausgabe wird trotzdem gewählt (band_only),
    # dann dürfen auch die Sonderausgaben nicht am Verlag scheitern
    regular = _marc_xml([("a", "Gachiakuta 15")], "Kazé Manga", "9783753945811", series=("Gachiakuta", "15"))
    schuber = _marc_xml([("a", "GACHIAKUTA 15 im Schuber")], "Kazé Manga", "9783759314086", series=("Gachiakuta", "15"))
    fake_dnb["responses"] = [_sru_response(), _sru_response(regular, schuber)]   # 1. Anfrage mit Verlag: nichts
    isbn, confidence, specials = isbn_lookup.lookup_isbn_dnb("Gachiakuta", 15, verlag="Carlsen Manga")
    assert (isbn, confidence) == ("9783753945811", "band_only")
    assert [s.isbn for s in specials] == ["9783759314086"]


def test_lookup_uses_unsaved_buffer_entries_instead_of_database(lookup_db, monkeypatch):
    seen = []
    def lookup(titel, band, *args, **kwargs):
        seen.append((titel, band))
        return "9783753945811", "dnb (band+verlag)", []

    monkeypatch.setattr(isbn_lookup, "lookup_isbn", lookup)
    # im Zwischenspeicher umbenannt und hochgezählt, aber noch nicht gespeichert
    entries = [{"id": -1, "titel": "Neu im Puffer", "baende_bis": "4", "voe_1": "TBA"}]

    report = isbn_lookup.fill_missing_isbns(lookup_db, only_status="TBA", entries=entries)

    assert seen == [("Neu im Puffer", 5)] and report.gesamt == 1
    assert _cached(lookup_db)["Neu im Puffer"] == "9783753945811"
    liste = isbn_lookup.bestellliste_markdown(lookup_db, status="TBA", entries=entries)
    assert "| TBA | Neu im Puffer |" in liste and "Alpha" not in liste

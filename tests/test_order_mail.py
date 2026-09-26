"""
tests/test_order_mail.py
Tests für order_mail.py: Bestell-E-Mail auslesen und Artikel den Einträgen
zuordnen. Die Test-Mail wird synthetisch erzeugt (keine echten Bestelldaten).
"""

import pytest

import order_mail

_ROW = (
    '<tr><td>{name}</td><td align="right">{qty}</td><td align="right">{price}</td><td></td></tr>'
    '<tr><td>Erscheinungstag: 01.09.2026</td></tr>'
)


def _html(*items):
    rows = "".join(_ROW.format(name=n, qty=q, price=p) for n, q, p in items)
    return (
        "<html><body><table>"
        "<tr><td>Bestellnummer</td><td>123</td></tr>"
        "<tr><td>Artikel</td><td>Anzahl</td><td>Preis</td></tr>"
        + rows + "</table></body></html>"
    )


def _entry(titel, baende):
    return {"titel": titel, "baende_bis": str(baende)}


def test_parse_html_reads_only_article_rows():
    items = order_mail.parse_html(_html(("Sanda - Band 12", 1, "9,00 EUR"), ("Fabiniku 14", 2, "9,00 EUR")))
    assert [(i.name, i.menge) for i in items] == [("Sanda - Band 12", 1), ("Fabiniku 14", 2)]


def test_parse_html_without_articles_raises():
    try:
        order_mail.parse_html("<html><body><table><tr><td>nichts</td></tr></table></body></html>")
    except ValueError:
        return
    raise AssertionError("ValueError erwartet")


def test_parse_eml_file(tmp_path):
    eml = tmp_path / "bestellung.eml"
    eml.write_text(
        "From: shop@example.org\nSubject: Bestellung\nMIME-Version: 1.0\n"
        'Content-Type: text/html; charset="UTF-8"\n\n' + _html(("Sanda - Band 12", 1, "9,00 EUR")),
        encoding="utf-8",
    )
    assert [i.name for i in order_mail.parse_eml(str(eml))] == ["Sanda - Band 12"]


def test_match_title_followed_by_band():
    entries = [_entry("Sanda", 11), _entry("Fabiniku", 13)]
    items = [order_mail.OrderItem("Sanda - Band 12"), order_mail.OrderItem("Fabiniku 14")]
    matches, owned, unmatched = order_mail.match_items(items, entries)
    assert [(m.entry["titel"], m.band) for m in matches] == [("Sanda", 12), ("Fabiniku", 14)]
    assert owned == [] and unmatched == []


def test_match_ignores_punctuation_case_and_trailing_text():
    entries = [_entry("Omniscient Reader's Viewpoint", 14)]
    items = [order_mail.OrderItem("OMNISCIENT READER’S VIEWPOINT - Band 15 im limitierten Sammelschuber")]
    matches, _, _ = order_mail.match_items(items, entries)
    assert len(matches) == 1 and matches[0].band == 15


def test_match_prefers_longest_title():
    entries = [_entry("Sanda", 11), _entry("Sanda Light Novel", 3)]
    matches, _, _ = order_mail.match_items([order_mail.OrderItem("Sanda Light Novel 4")], entries)
    assert matches[0].entry["titel"] == "Sanda Light Novel"


def test_match_subtitle_only_when_number_is_next_band():
    entries = [_entry("Togen Anki", 22)]
    ok, _, _ = order_mail.match_items([order_mail.OrderItem("Togen Anki - Teufelsblut 23")], entries)
    assert len(ok) == 1 and ok[0].band == 23
    _, _, unmatched = order_mail.match_items([order_mail.OrderItem("Togen Anki - Teufelsblut 30")], entries)
    assert len(unmatched) == 1


def test_already_owned_band_is_not_marked():
    entries = [_entry("Sanda", 12)]
    matches, owned, _ = order_mail.match_items([order_mail.OrderItem("Sanda - Band 12")], entries)
    assert matches == [] and len(owned) == 1


def test_title_must_match_whole_word():
    entries = [_entry("San", 1)]
    _, _, unmatched = order_mail.match_items([order_mail.OrderItem("Sanda 2")], entries)
    assert len(unmatched) == 1


_PICKUP_HTML = (
    "<html><body><table>"
    "<tr><td>Folgende Artikel Ihrer Bestellung wurden f&uuml;r die Auslieferung an Ihre Buchhandlung "
    "zusammengestellt und stehen <b>zur Abholung</b> bereit.</td></tr>"
    "<tr><td><table>"
    "<tr><td><b>Artikel</b></td><td><b>Menge</b></td></tr>"
    "<tr><td>Rairairai 04-EAN:9783755507260</td><td>1</td></tr>"
    "<tr><td>Sanda - Band 12-EAN:9781234567890</td><td>1</td></tr>"
    "</table></td></tr>"
    "<tr><td>Anzahl bestellte Exemplare:</td><td>2</td></tr>"
    "<tr><td><table>"
    "<tr><td>Nr</td><td>Artikel</td><td>Best. Exempl.</td><td>Gelief. Exempl.</td><td>Status</td></tr>"
    "<tr><td>1</td><td>Rairairai 04- EAN:9783755507260</td><td>1</td><td>1</td><td>komplett ausgeliefert</td></tr>"
    "</table></td></tr>"
    "</table></body></html>"
)


def test_parse_pickup_mail_reads_article_table_once_and_strips_ean():
    items = order_mail.parse_html(_PICKUP_HTML)
    assert [(i.name, i.kind) for i in items] == [
        ("Rairairai 04", order_mail.KIND_PICKUP),
        ("Sanda - Band 12", order_mail.KIND_PICKUP),
    ]


def test_order_confirmation_is_not_treated_as_pickup():
    # auch wenn im Mailtext "abholbereit"/"Abholung" vorkommt: Preise => Bestellbestätigung
    html = _html(("Sanda - Band 12", 1, "9,00 EUR")).replace("<table>", "<p>Sobald Ihre Bestellung abholbereit ist ... zur Abholung bereit</p><table>", 1)
    items = order_mail.parse_html(html)
    assert [i.kind for i in items] == [order_mail.KIND_ORDER]


def test_pickup_items_match_entries_like_orders():
    entries = [_entry("Rairairai", 3), _entry("Sanda", 11)]
    items = order_mail.parse_html(_PICKUP_HTML)
    matches, owned, unmatched = order_mail.match_items(items, entries)
    assert [(m.entry["titel"], m.band, m.item.kind) for m in matches] == [
        ("Rairairai", 4, order_mail.KIND_PICKUP),
        ("Sanda", 12, order_mail.KIND_PICKUP),
    ]
    assert owned == [] and unmatched == []


def test_order_and_pickup_for_same_title_are_both_kept():
    entries = [_entry("Sanda", 11)]
    items = [
        order_mail.OrderItem("Sanda - Band 12", kind=order_mail.KIND_ORDER),
        order_mail.OrderItem("Sanda - Band 12", kind=order_mail.KIND_PICKUP),
    ]
    matches, _, _ = order_mail.match_items(items, entries)
    assert sorted(m.item.kind for m in matches) == sorted([order_mail.KIND_ORDER, order_mail.KIND_PICKUP])


def test_build_log_has_separate_section_for_unmatched_articles_and_no_personal_data():
    entries = [_entry("Sanda", 11), _entry("Fabiniku", 14)]
    items = [
        order_mail.OrderItem("Sanda - Band 12"),
        order_mail.OrderItem("Fabiniku 14"),                      # Band schon im Bestand
        order_mail.OrderItem("Sonderedition Schuber Deluxe", 2),  # ohne Eintrag
    ]
    matches, owned, unmatched = order_mail.match_items(items, entries)
    lines = order_mail.build_log("Postfach (IMAP)", 1, items, matches, matches, owned, unmatched,
                                 problems=["Datei 2: keine Artikelliste"])
    text = "\n".join(lines)
    assert "Quelle:                   Postfach (IMAP)" in text
    assert "Sanda | Band 12 | Artikel: Sanda - Band 12" in text
    assert "Fabiniku | Band 14 | Bände (bis) = 14" in text
    assert "--- Nicht lesbare Dateien (1) ---" in text
    # der eigene Abschnitt für Artikel ohne Eintrag steht am Ende
    head, _, tail = text.partition("--- ARTIKEL OHNE PASSENDEN EINTRAG (1) ---")
    assert "Sonderedition Schuber Deluxe | Menge 2 | bestellt" in tail
    assert "Sonderedition" not in head


def test_build_log_lists_none_when_everything_matched():
    entries = [_entry("Sanda", 11)]
    items = [order_mail.OrderItem("Sanda - Band 12")]
    matches, owned, unmatched = order_mail.match_items(items, entries)
    text = "\n".join(order_mail.build_log("Datei", 1, items, matches, matches, owned, unmatched))
    assert "--- ARTIKEL OHNE PASSENDEN EINTRAG (0) ---\n  (keine)" in text


# --------------------------------------------- Markierung mit Bandnummer (Feld-Wert)

def test_match_keeps_highest_band_per_title_and_kind():
    entries = [_entry("Sanda", 11)]
    items = [order_mail.OrderItem("Sanda - Band 12"), order_mail.OrderItem("Sanda - Band 13")]
    matches, _, _ = order_mail.match_items(items, entries)
    assert [(m.entry["titel"], m.band) for m in matches] == [("Sanda", 13)]


def _match(entry, band, kind=order_mail.KIND_ORDER):
    return order_mail.Match(order_mail.OrderItem(f"{entry['titel']} {band}", kind=kind), entry, band)


def test_new_marks_only_for_unmarked_or_higher_band():
    unmarked = {"titel": "A", "baende_bis": "11"}
    lower = {"titel": "B", "baende_bis": "11", "bestellt": "12"}
    same = {"titel": "C", "baende_bis": "11", "bestellt": "13"}
    higher = {"titel": "D", "baende_bis": "11", "bestellt": "14"}
    pickup = {"titel": "E", "baende_bis": "11", "bestellt": "13"}   # bestellt gesetzt, angekommen noch nicht
    matches = [
        _match(unmarked, 13), _match(lower, 13), _match(same, 13), _match(higher, 13),
        _match(pickup, 13, order_mail.KIND_PICKUP),
    ]
    assert [m.entry["titel"] for m in order_mail.new_marks(matches)] == ["A", "B", "E"]


def test_parse_message_with_unknown_charset_raises_value_error():
    raw = (
        b"From: shop@example.org\nSubject: Bestellung\nMIME-Version: 1.0\n"
        b'Content-Type: text/html; charset="x-gibt-es-nicht"\n\n<html><body>kaputt</body></html>'
    )
    with pytest.raises(ValueError, match="nicht gelesen werden"):
        order_mail.parse_message_bytes(raw)

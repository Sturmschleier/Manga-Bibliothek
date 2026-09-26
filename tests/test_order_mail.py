"""
tests/test_order_mail.py
Tests für order_mail.py: Bestell-E-Mail auslesen und Artikel den Einträgen
zuordnen. Die Test-Mail wird synthetisch erzeugt (keine echten Bestelldaten).
"""

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

"""
tests/test_shops.py
Tests für die Auswahl des Bestell-Buchhändlers (shops.py) und die
Bestellliste (isbn_lookup.bestellliste_markdown).
"""

import pytest

import config
import database as db
import isbn_lookup
import shops


@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")


def test_default_shop_is_konold_and_thalia_is_offered():
    assert list(shops.available()) == ["Konold", "Thalia", "Amazon"]
    assert shops.active_name() == "Konold"
    assert "konold.buchhandlung.de" in shops.order_url("9783551795274")


def test_thalia_link_uses_isbn_search():
    shops.set_active("Thalia")
    assert shops.active_name() == "Thalia"
    assert shops.order_url("9783551795274") == "https://www.thalia.de/suche?sq=9783551795274"


def test_amazon_link_uses_isbn_search():
    shops.set_active("Amazon")
    assert shops.active_name() == "Amazon"
    assert shops.order_url("9783551795274") == "https://www.amazon.de/s?k=9783551795274"


def test_unknown_saved_shop_falls_back_to_default():
    config.set_value("isbn_shop_active", "GibtEsNicht")
    assert shops.active_name() == "Konold"
    shops.set_active("AuchNicht")          # unbekannte Namen werden nicht gespeichert
    assert config.get("isbn_shop_active") == "GibtEsNicht"


def test_custom_default_shop_from_config_is_first_choice():
    config.set_value("isbn_shop_name", "MeinShop")
    config.set_value("isbn_shop_url_template", "https://shop.example/{isbn}")
    assert list(shops.available()) == ["MeinShop", "Thalia", "Amazon"]
    assert shops.order_url("123") == "https://shop.example/123"
    assert shops.order_url("123", "Thalia").endswith("sq=123")


def test_bestellliste_links_to_selected_shop(tmp_path, monkeypatch):
    db_file = tmp_path / "manga_library.db"
    monkeypatch.setattr(db, "DB_FILE", db_file)
    db.init_db()
    db.replace_all([{"titel": "NARUTO Massiv", "verlag": "Carlsen", "baende_bis": "0", "voe_1": "01.09.2026"}])
    isbn_lookup.ensure_isbn_cache_table(str(db_file))
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO isbn_cache (titel, baende_bis, isbn, gefunden_am) VALUES (?, ?, ?, ?)",
        ("NARUTO Massiv", "0", "9783551795274", "2026-09-01"),
    )
    conn.commit()
    conn.close()

    konold = isbn_lookup.bestellliste_markdown(str(db_file), 9, 2026)
    assert "Buchhändler: Konold" in konold and "konold.buchhandlung.de" in konold

    shops.set_active("Thalia")
    thalia = isbn_lookup.bestellliste_markdown(str(db_file), 9, 2026)
    assert "Buchhändler: Thalia" in thalia
    assert "https://www.thalia.de/suche?sq=9783551795274" in thalia


def test_other_braces_in_template_do_not_break_links():
    config.set_value("isbn_shop_url_template", "https://shop.example/{isbn}?utm={quelle}")
    assert shops.order_url("123") == "https://shop.example/123?utm={quelle}"

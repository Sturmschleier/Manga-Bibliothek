"""
tests/test_database.py
Tests für die Schema-Migration auf Version 2 (Entfernen von VÖ +4 / VÖ +5).
"""

import sqlite3

import database as db


def _make_v1_database(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE werke (id INTEGER PRIMARY KEY AUTOINCREMENT, titel TEXT, baende_bis TEXT, "
        "komplett TEXT, beendet TEXT, gelesen_bis TEXT, typ TEXT, zugang TEXT, verlag TEXT, "
        "kommentar TEXT, voe_1 TEXT, voe_2 TEXT, voe_3 TEXT, voe_4 TEXT, voe_5 TEXT)"
    )
    conn.execute(
        "INSERT INTO werke (titel, voe_1, voe_2, voe_3, voe_4, voe_5) VALUES ('Alt', 'TBA', 'a', 'b', 'c', 'd')"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_columns_no_longer_contain_voe_4_and_5():
    assert "voe_4" not in db.COLUMN_NAMES
    assert "voe_5" not in db.COLUMN_NAMES
    assert "voe_4" not in db.LABELS
    assert "voe_5" not in db.LABELS


def test_migration_drops_columns_keeps_other_data_and_makes_backup(tmp_path, monkeypatch):
    db_file = tmp_path / "manga_library.db"
    _make_v1_database(db_file)
    monkeypatch.setattr(db, "DB_FILE", db_file)

    db.init_db()

    conn = sqlite3.connect(db_file)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(werke)").fetchall()}
    assert "voe_4" not in cols and "voe_5" not in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("SELECT titel, voe_1, voe_2, voe_3 FROM werke").fetchall() == [("Alt", "TBA", "a", "b")]
    conn.close()

    backup = tmp_path / "manga_library.db.vor-schema-v2.bak"
    assert backup.exists()
    bconn = sqlite3.connect(backup)
    assert bconn.execute("SELECT voe_4, voe_5 FROM werke").fetchall() == [("c", "d")]
    bconn.close()


def test_fresh_database_needs_no_backup(tmp_path, monkeypatch):
    db_file = tmp_path / "manga_library.db"
    monkeypatch.setattr(db, "DB_FILE", db_file)

    db.init_db()

    assert not (tmp_path / "manga_library.db.vor-schema-v2.bak").exists()
    assert [e for e in db.load_all()] == []


def test_hidden_column_bestellt_is_stored_but_not_a_visible_column(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "manga_library.db")
    db.init_db()
    assert "bestellt" not in db.COLUMN_NAMES
    assert "bestellt" in db.STORED_COLUMN_NAMES

    loaded = db.replace_all([{"titel": "A", "bestellt": "1", "angekommen": "1"}, {"titel": "B"}])
    assert {e["titel"]: (e["bestellt"], e["angekommen"]) for e in loaded} == {"A": ("1", "1"), "B": ("", "")}

"""
tests/test_database.py
Tests für die Schema-Migration auf Version 2 (Entfernen von VÖ +4 / VÖ +5),
das atomare Speichern, die Datenbank-Sicherungen und den Austausch der
Datenbankdatei (Google-Drive-Download).
"""

import sqlite3

import pytest

import config
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


# ---------------------------------------------------------------------------
# Speichern ist atomar, Sicherungen, Austausch der Datenbankdatei
# ---------------------------------------------------------------------------

@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "manga_library.db")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    db.init_db()
    db.replace_all([{"titel": "Alt"}])
    return tmp_path


def _make_library_db(path, titel):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE werke (id INTEGER PRIMARY KEY, titel TEXT)")
    conn.execute("INSERT INTO werke (titel) VALUES (?)", (titel,))
    conn.commit()
    conn.close()


def _titles(path):
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT titel FROM werke")]
    finally:
        conn.close()


def test_replace_all_rolls_back_completely_on_error(db_env):
    with pytest.raises(sqlite3.Error):
        db.replace_all([{"titel": "Neu"}, {"titel": ["kein", "Text"]}])  # zweite Zeile nicht speicherbar
    assert [e["titel"] for e in db.load_all()] == ["Alt"]           # nichts gelöscht, nichts halb geschrieben


def test_create_backup_copies_current_database(db_env):
    path = db.create_backup("vor-speichern")
    assert path.parent == db_env / "BACKUP"
    assert path.name.startswith("manga_library_") and path.name.endswith("_vor-speichern.db")
    assert _titles(path) == ["Alt"]


def test_create_backup_without_database_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "manga_library.db")
    assert db.create_backup("vor-speichern") is None
    assert not (tmp_path / "BACKUP").exists()


def test_create_backup_keeps_only_newest(db_env):
    folder = db_env / "BACKUP"
    folder.mkdir()
    for day in (1, 2, 3):
        (folder / f"manga_library_2026-01-0{day}_10-00-00-000_vor-speichern.db").write_text("alt")
    (folder / "eigene-notiz.txt").write_text("bleibt")

    newest = db.create_backup("vor-speichern", keep=2)

    names = sorted(p.name for p in folder.glob("manga_library_*.db"))
    assert names == ["manga_library_2026-01-03_10-00-00-000_vor-speichern.db", newest.name]
    assert (folder / "eigene-notiz.txt").exists()                  # fremde Dateien bleiben unangetastet


def test_create_backup_default_keep_comes_from_config(db_env):
    config.set_value("db_backup_keep", 1)
    db.create_backup("a")
    db.create_backup("b")
    assert len(list((db_env / "BACKUP").glob("manga_library_*.db"))) == 1


def test_replace_database_file_swaps_and_backs_up_old_one(db_env):
    new_file = db_env / "manga_library.db.download"
    _make_library_db(new_file, "Aus Drive")

    backup_path = db.replace_database_file(new_file, reason="vor-download")

    assert _titles(db.DB_FILE) == ["Aus Drive"]
    assert not new_file.exists()
    assert backup_path.endswith("_vor-download.db") and _titles(backup_path) == ["Alt"]


@pytest.mark.parametrize("content", [b"", b"das ist keine Datenbank" * 50])
def test_replace_database_file_rejects_broken_file_and_keeps_local(db_env, content):
    new_file = db_env / "manga_library.db.download"
    new_file.write_bytes(content)

    with pytest.raises(ValueError, match="unverändert"):
        db.replace_database_file(new_file, reason="vor-download")

    assert _titles(db.DB_FILE) == ["Alt"]
    assert not (db_env / "BACKUP").exists()                        # abgelehnt, bevor etwas angefasst wird


def test_replace_database_file_rejects_database_without_library_table(db_env):
    new_file = db_env / "manga_library.db.download"
    conn = sqlite3.connect(new_file)
    conn.execute("CREATE TABLE etwas_anderes (x TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="werke"):
        db.replace_database_file(new_file, reason="vor-download")
    assert _titles(db.DB_FILE) == ["Alt"]

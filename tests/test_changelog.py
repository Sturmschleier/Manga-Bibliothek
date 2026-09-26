"""
tests/test_changelog.py
Tests für die Log-Verwaltung (changelog.py): ISBN-Logdateien begrenzen,
Änderungsprotokoll archivieren.
"""

from datetime import datetime, timedelta

import pytest

import changelog
import config


@pytest.fixture
def log_env(tmp_path, monkeypatch):
    log_dir = tmp_path / "LOG"
    log_dir.mkdir()
    monkeypatch.setattr(changelog, "LOG_DIR", log_dir)
    monkeypatch.setattr(changelog, "CHANGELOG_FILE", log_dir / "aenderungen.log")
    monkeypatch.setattr(changelog, "ARCHIVE_FILE", log_dir / "aenderungen_archiv.log")
    monkeypatch.setattr(changelog, "ERROR_LOG_FILE", log_dir / "fehler.log")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    return log_dir


def _isbn_logs(log_dir, count):
    for i in range(count):
        (log_dir / f"isbn_abgleich_2026-09-{i + 1:02d}_10-00-00.log").write_text("x")


def _line(days_ago, text="Änderung"):
    ts = datetime.now() - timedelta(days=days_ago)
    return f"[{ts.strftime('%Y-%m-%d %H:%M:%S')}] {text}"


def test_prune_keeps_only_newest_default_ten(log_env):
    _isbn_logs(log_env, 16)
    (log_env / "aenderungen.log").write_text("[2026-01-01 00:00:00] x\n")
    assert changelog.prune_isbn_logs() == 6
    remaining = sorted(p.name for p in log_env.glob("isbn_abgleich_*.log"))
    assert len(remaining) == 10
    assert remaining[0] == "isbn_abgleich_2026-09-07_10-00-00.log"   # die 6 ältesten sind weg
    assert (log_env / "aenderungen.log").exists()                       # andere Logs bleiben unberührt


def test_prune_uses_configured_count(log_env):
    _isbn_logs(log_env, 8)
    config.set_value("isbn_log_keep", 3)
    assert changelog.prune_isbn_logs() == 5
    assert len(list(log_env.glob("isbn_abgleich_*.log"))) == 3


def test_prune_keeps_at_least_one_and_ignores_garbage_config(log_env):
    _isbn_logs(log_env, 4)
    config.set_value("isbn_log_keep", 0)
    changelog.prune_isbn_logs()
    assert len(list(log_env.glob("isbn_abgleich_*.log"))) == 1
    _isbn_logs(log_env, 15)
    config.set_value("isbn_log_keep", "abc")     # kaputter Wert -> Standard 10
    changelog.prune_isbn_logs()
    assert len(list(log_env.glob("isbn_abgleich_*.log"))) == 10


def test_prune_without_log_dir_does_not_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(changelog, "LOG_DIR", tmp_path / "gibt-es-nicht")
    assert changelog.prune_isbn_logs() == 0


def test_archive_uses_configured_retention_days(log_env):
    (log_env / "aenderungen.log").write_text("\n".join([_line(40, "alt"), _line(3, "neu")]) + "\n", encoding="utf-8")
    config.set_value("log_retention_days", 30)
    assert changelog.archive_old_entries() == 1
    assert "neu" in (log_env / "aenderungen.log").read_text(encoding="utf-8")
    assert "alt" in (log_env / "aenderungen_archiv.log").read_text(encoding="utf-8")


def test_archive_default_is_182_days(log_env):
    (log_env / "aenderungen.log").write_text(_line(100, "mittel") + "\n" + _line(200, "uralt") + "\n", encoding="utf-8")
    assert changelog.archive_old_entries() == 1


def test_config_get_int_falls_back_on_garbage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    config.set_value("isbn_log_keep", "zehn")
    assert config.get_int("isbn_log_keep") == 10
    config.set_value("isbn_log_keep", "7")
    assert config.get_int("isbn_log_keep") == 7


def test_write_order_log_creates_file_and_keeps_only_configured_number(log_env):
    config.set_value("order_log_keep", 3)
    paths = [changelog.write_order_log([f"Vorgang {i}"]) for i in range(6)]
    files = sorted(p.name for p in log_env.glob("bestellung_einlesen_*.log"))
    assert len(files) == 3                                     # nur die neuesten 3 bleiben liegen
    assert all(f.startswith("bestellung_einlesen_") for f in files)
    assert (log_env / files[-1]).read_text(encoding="utf-8").strip() == "Vorgang 5"
    assert len(set(paths)) == 6                                # gleiche Sekunde überschreibt nichts


def test_order_log_default_keep_is_ten_and_other_logs_untouched(log_env):
    for i in range(14):
        (log_env / f"bestellung_einlesen_2026-09-{i + 1:02d}_10-00-00.log").write_text("x")
    _isbn_logs(log_env, 12)
    assert changelog.prune_order_logs() == 4
    assert len(list(log_env.glob("bestellung_einlesen_*.log"))) == 10
    assert len(list(log_env.glob("isbn_abgleich_*.log"))) == 12   # ISBN-Logs haben ihre eigene Grenze


def test_log_error_appends_traceback_with_timestamp(log_env):
    path = changelog.log_error("Traceback …\nValueError: kaputt\n")
    changelog.log_error("Traceback …\nKeyError: weg")
    text = (log_env / "fehler.log").read_text(encoding="utf-8")
    assert path == str(log_env / "fehler.log")
    assert text.startswith("[") and "ValueError: kaputt" in text and "KeyError: weg" in text


def test_log_error_returns_none_if_not_writable(log_env, monkeypatch):
    monkeypatch.setattr(changelog, "ERROR_LOG_FILE", log_env)  # ein Ordner lässt sich nicht als Datei öffnen
    assert changelog.log_error("x") is None


def test_write_isbn_log_names_files_uniquely_and_keeps_configured_number(log_env):
    config.set_value("isbn_log_keep", 2)
    paths = [changelog.write_isbn_log([f"Abgleich {i}"]) for i in range(4)]
    files = sorted(p.name for p in log_env.glob("isbn_abgleich_*.log"))
    assert len(set(paths)) == 4 and len(files) == 2
    assert (log_env / files[-1]).read_text(encoding="utf-8").strip() == "Abgleich 3"

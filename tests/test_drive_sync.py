"""
tests/test_drive_sync.py
Tests für den Google-Drive-Download (drive_sync.download): die lokale
Datenbank darf erst ersetzt werden, wenn die heruntergeladene Datei
vollständig und intakt ist. Die Google-API wird dabei nicht angesprochen.
"""

import sqlite3

import pytest

pytest.importorskip("googleapiclient")

import config  # noqa: E402
import database as db  # noqa: E402
import drive_sync  # noqa: E402


class _FakeDownloader:
    """Ersatz für MediaIoBaseDownload: schreibt `payload` in Stücken und
    bricht auf Wunsch nach dem ersten Stück mit einem Netzwerkfehler ab."""

    payload = b""
    fail_after_first_chunk = False

    def __init__(self, fh, _request):
        self.fh = fh
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        if self.calls == 1:
            self.fh.write(self.payload[: len(self.payload) // 2])
            return None, False
        if self.fail_after_first_chunk:
            raise ConnectionError("Verbindung abgebrochen")
        self.fh.write(self.payload[len(self.payload) // 2:])
        return None, True


class _FakeService:
    def files(self):
        return self

    def get_media(self, fileId):
        return object()


@pytest.fixture
def drive_env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "manga_library.db")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    db.init_db()
    db.replace_all([{"titel": "Lokal"}])

    monkeypatch.setattr(drive_sync, "_get_service", lambda: _FakeService())
    monkeypatch.setattr(drive_sync, "_find_folder_id", lambda service: "ordner")
    monkeypatch.setattr(drive_sync, "_find_db_file_id", lambda service, folder_id: "datei")
    monkeypatch.setattr(drive_sync, "MediaIoBaseDownload", _FakeDownloader)
    monkeypatch.setattr(_FakeDownloader, "fail_after_first_chunk", False)
    return tmp_path


def _drive_copy_bytes(tmp_path, titel):
    path = tmp_path / "drive_version.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE werke (id INTEGER PRIMARY KEY, titel TEXT)")
    conn.execute("INSERT INTO werke (titel) VALUES (?)", (titel,))
    conn.commit()
    conn.close()
    return path.read_bytes()


def _local_titles():
    return [e["titel"] for e in db.load_all()]


def test_download_replaces_local_database_and_keeps_backup(drive_env, monkeypatch):
    monkeypatch.setattr(_FakeDownloader, "payload", _drive_copy_bytes(drive_env, "Aus Drive"))

    backup_path = drive_sync.download()

    assert _local_titles() == ["Aus Drive"]
    assert backup_path and "vor-download" in backup_path
    assert not (drive_env / "manga_library.db.download").exists()


def test_interrupted_download_leaves_local_database_untouched(drive_env, monkeypatch):
    monkeypatch.setattr(_FakeDownloader, "payload", _drive_copy_bytes(drive_env, "Aus Drive"))
    monkeypatch.setattr(_FakeDownloader, "fail_after_first_chunk", True)

    with pytest.raises(ConnectionError):
        drive_sync.download()

    assert _local_titles() == ["Lokal"]
    assert not (drive_env / "manga_library.db.download").exists()
    assert not (drive_env / "BACKUP").exists()


def test_broken_download_is_rejected_and_local_database_untouched(drive_env, monkeypatch):
    monkeypatch.setattr(_FakeDownloader, "payload", b"<html>Fehlerseite statt Datenbank</html>" * 20)

    with pytest.raises(drive_sync.DriveSyncError, match="unverändert"):
        drive_sync.download()

    assert _local_titles() == ["Lokal"]
    assert not (drive_env / "manga_library.db.download").exists()

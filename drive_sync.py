"""
drive_sync.py
Sichert die lokale SQLite-Datenbankdatei in Google Drive bzw. stellt sie von
dort wieder her. Nutzt die offizielle Google-API-Client-Bibliothek mit
OAuth2 (Anmeldung im Browser, einmalig).

Voraussetzung (siehe README.md):
1. In der Google Cloud Console ein Projekt anlegen, "Google Drive API"
   aktivieren und OAuth-Client-Zugangsdaten (Desktop-App) erstellen.
2. Die heruntergeladene Datei als "credentials.json" in diesen Ordner legen.
3. Beim ersten Sync öffnet sich ein Browserfenster zur Anmeldung; danach wird
   ein Token lokal in "token.json" gespeichert (keine erneute Anmeldung nötig).

Die Datenbank wird in Drive in einem Ordner "MangaLibrary" unter dem Namen
"manga_library.db" abgelegt. Es wird immer dieselbe Datei aktualisiert
(kein Duplikat pro Sync).

Beim Herunterladen wird die lokale Datenbank erst ersetzt, wenn die Datei
vollständig angekommen und als intakte Datenbank geprüft ist; die bisherige
lokale Datenbank wird vorher nach BACKUP/ gesichert (siehe download()).
"""

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import database as db
from paths import base_dir

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

BASE_DIR = base_dir()
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
LOGIN_TIMEOUT_SECONDS = 300   # so lange wartet die erste Anmeldung auf den Browser
DRIVE_FOLDER_NAME = "MangaLibrary"
DRIVE_FILE_NAME = "manga_library.db"


class DriveSyncError(Exception):
    pass


def _get_credentials():
    if not CREDENTIALS_FILE.exists():
        raise DriveSyncError(
            "credentials.json wurde nicht gefunden. Bitte gemäß README.md "
            "OAuth-Zugangsdaten aus der Google Cloud Console herunterladen "
            "und als credentials.json in diesem Ordner ablegen."
        )

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except ValueError:
            creds = None  # kaputte token.json -> neu anmelden

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None  # Token abgelaufen/widerrufen -> neu anmelden
        if not creds or not creds.valid:
            creds = _login()
        TOKEN_FILE.write_text(creds.to_json())

    return creds


def _login():
    """Anmeldung im Browser. Wird sie nicht innerhalb von LOGIN_TIMEOUT_SECONDS
    abgeschlossen, bricht der Vorgang mit einer verständlichen Meldung ab,
    statt endlos zu warten."""
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    try:
        creds = flow.run_local_server(port=0, timeout_seconds=LOGIN_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - Zeitüberschreitung, abgelehnte Anmeldung ...
        raise DriveSyncError(
            f"Die Google-Anmeldung wurde nicht abgeschlossen ({exc}). Bitte erneut versuchen "
            f"und die Anmeldung im Browser innerhalb von {LOGIN_TIMEOUT_SECONDS // 60} Minuten bestätigen."
        ) from exc
    if creds is None:
        raise DriveSyncError("Die Google-Anmeldung wurde nicht abgeschlossen. Bitte erneut versuchen.")
    return creds


def _get_service():
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


def _find_folder_id(service):
    query = (
        f"name = '{DRIVE_FOLDER_NAME}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": DRIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def _find_db_file_id(service, folder_id):
    query = f"name = '{DRIVE_FILE_NAME}' and '{folder_id}' in parents and trashed = false"
    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def upload():
    """Lädt die lokale DB-Datei nach Google Drive hoch (erstellt oder aktualisiert)."""
    if not db.DB_FILE.exists():
        raise DriveSyncError("Es existiert noch keine lokale Datenbank zum Hochladen.")

    service = _get_service()
    folder_id = _find_folder_id(service)
    file_id = _find_db_file_id(service, folder_id)
    media = MediaFileUpload(str(db.DB_FILE), mimetype="application/x-sqlite3", resumable=True)

    try:
        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            metadata = {"name": DRIVE_FILE_NAME, "parents": [folder_id]}
            service.files().create(body=metadata, media_body=media, fields="id").execute()
    finally:
        # MediaFileUpload hält die Datei sonst offen, bis es vom Garbage
        # Collector eingesammelt wird - unter Windows würde das ein späteres
        # Ersetzen der Datenbankdatei (download()) blockieren.
        media.stream().close()


def download():
    """
    Lädt die DB-Datei von Google Drive herunter und ersetzt damit die lokale
    Datenbank.

    Heruntergeladen wird zunächst in eine temporäre Datei neben der
    Datenbank. Erst wenn sie vollständig ist und sich als intakte
    Bibliotheks-Datenbank erweist, wird die bisherige lokale Datenbank nach
    BACKUP/ gesichert und ersetzt (siehe database.replace_database_file).
    Bricht der Download ab oder ist die Datei unbrauchbar, bleibt die lokale
    Datenbank unverändert.

    Gibt den Pfad der Sicherung der bisherigen lokalen Datenbank zurück
    (oder None, wenn es noch keine gab).
    """
    service = _get_service()
    folder_id = _find_folder_id(service)
    file_id = _find_db_file_id(service, folder_id)
    if not file_id:
        raise DriveSyncError("In Google Drive wurde keine Sicherung gefunden.")

    tmp_path = db.DB_FILE.with_name(db.DB_FILE.name + ".download")
    request = service.files().get_media(fileId=file_id)
    try:
        with open(tmp_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        try:
            return db.replace_database_file(tmp_path, reason="vor-download")
        except ValueError as exc:
            raise DriveSyncError(f"Die Sicherung aus Google Drive ist unbrauchbar: {exc}") from exc
    finally:
        try:
            tmp_path.unlink(missing_ok=True)  # nach erfolgreichem Austausch existiert sie nicht mehr
        except OSError:
            pass

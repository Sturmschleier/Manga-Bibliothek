"""
database.py
Kapselt den SQLite-Zugriff der Manga/Light-Novel-Bibliothek.

Die GUI arbeitet mit einem Puffer im Speicher (Liste von Dicts); die
Datenbank wird nur beim Start gelesen (load_all) und beim aktiven Speichern
komplett neu geschrieben (replace_all). Es gibt bewusst keine Funktionen,
die einzelne Zeilen sofort in die Datenbank schreiben.

Bevor die Datenbankdatei überschrieben wird (Speichern, Google-Drive-
Download), legt der Aufrufer mit create_backup() eine Sicherung im Ordner
BACKUP/ neben der Datenbank an; es bleiben nur die neuesten
`db_backup_keep` Sicherungen liegen (config.json, Standard 20).
"""

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Optional

import config
from paths import base_dir

DB_FILE = base_dir() / "manga_library.db"
BACKUP_DIR_NAME = "BACKUP"
BACKUP_PREFIX = "manga_library_"

# Schema-Versionierung über SQLites eingebautes PRAGMA user_version (ein
# einzelner Integer, direkt im Datenbank-Header gespeichert - kein
# zusätzliches Tabellen-Setup nötig). Ergänzt die bisherige Spalten-
# Migration (ALTER TABLE ADD COLUMN, siehe init_db) um einen Ort für
# STRUKTURELLE Änderungen (z.B. Spalten entfernen, eine Tabelle aufteilen),
# die sich nicht mehr mit einem einfachen "fehlende Spalte ergänzen"
# abbilden lassen - siehe _apply_migrations().
#   1 = Ausgangszustand (mit VÖ +4 / VÖ +5)
#   2 = Spalten voe_4 und voe_5 entfernt
#   3 = bestellt/angekommen enthalten die Bandnummer statt "1"
SCHEMA_VERSION = 3

# Seit Schema-Version 2 nicht mehr Teil des Datenmodells; werden bei
# bestehenden Datenbanken in _apply_migrations() entfernt.
_REMOVED_COLUMNS_V2 = ("voe_4", "voe_5")

# Spalten exakt wie in der ursprünglichen CSV (nur intern umbenannt, da
# "bis" u.ä. keine sprechenden Namen sind).
COLUMNS = [
    ("titel", "TEXT"),
    ("baende_bis", "TEXT"),      # "bis" - Anzahl vorhandener Bände
    ("komplett", "TEXT"),        # Ja/Nein
    ("beendet", "TEXT"),         # Ja/Nein
    ("gelesen_bis", "TEXT"),
    ("typ", "TEXT"),             # Manga / Manhwa / Light Novel
    ("zugang", "TEXT"),          # MM.JJJJ
    ("verlag", "TEXT"),
    ("kommentar", "TEXT"),
    ("voe_1", "TEXT"),
    ("voe_2", "TEXT"),
    ("voe_3", "TEXT"),
]

COLUMN_NAMES = [c[0] for c in COLUMNS]

# Die Erscheinungstermine in ihrer Reihenfolge (VÖ +1 = nächster Band) -
# einzige Quelle für "+1" (logic.py), Sortierung (sorting.py) und die
# Termin-Zähler der Seitenleiste (gui/constants.py).
VOE_COLUMNS = ("voe_1", "voe_2", "voe_3")

# Zusätzlich gespeicherte, aber NICHT sichtbare Felder: gehören zum
# Eintrag (Puffer, Undo, Speichern), erscheinen aber weder als Tabellen-
# spalte noch im Bearbeiten-Formular oder im CSV-Export/-Import.
#   bestellt = Bandnummer (z.B. "14"), wenn dieser Band laut Bestell-
#              bestätigung (E-Mail-Import, siehe order_mail.py) bestellt
#              wurde - wird in der Tabelle hellblau am Titel markiert.
#   angekommen = Bandnummer, wenn dieser Band laut Abhol-Benachrichtigung
#              (E-Mail, siehe order_mail.py) in der Buchhandlung abholbereit
#              ist - roter Balken links an der Titelzelle.
#   Beide entfallen, sobald "Bände (bis)" den markierten Band erreicht
#   (siehe logic.clear_fulfilled_marks).
HIDDEN_COLUMNS = [
    ("bestellt", "TEXT"),
    ("angekommen", "TEXT"),
]
STORED_COLUMNS = COLUMNS + HIDDEN_COLUMNS
STORED_COLUMN_NAMES = [c[0] for c in STORED_COLUMNS]

# Sprechende Beschriftungen für die GUI
LABELS = {
    "titel": "Titel",
    "baende_bis": "Bände (bis)",
    "komplett": "Komplett",
    "beendet": "Beendet",
    "gelesen_bis": "Gelesen bis",
    "typ": "Typ",
    "zugang": "Zugang",
    "verlag": "Verlag",
    "kommentar": "Kommentar",
    "voe_1": "VÖ +1",
    "voe_2": "VÖ +2",
    "voe_3": "VÖ +3",
}


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _apply_migrations(conn, current_version: int) -> None:
    """
    Führt alle noch ausstehenden strukturellen Schema-Migrationen aus
    (Versionen zwischen `current_version` und SCHEMA_VERSION).

    Version 2: entfernt die Spalten voe_4 und voe_5 (VÖ +4 / VÖ +5). Da
    dabei eventuell vorhandene Inhalte dieser Spalten endgültig verloren
    gehen, wird vorher - nur wenn die Spalten tatsächlich noch existieren -
    eine Sicherungskopie der Datenbank neben der Datenbankdatei angelegt.
    """
    if current_version < 2:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(werke)").fetchall()}
        to_drop = [c for c in _REMOVED_COLUMNS_V2 if c in existing]
        if to_drop:
            backup_path = DB_FILE.with_name(DB_FILE.name + ".vor-schema-v2.bak")
            backup = sqlite3.connect(backup_path)
            try:
                conn.backup(backup)
            finally:
                backup.close()
            for col in to_drop:
                conn.execute(f"ALTER TABLE werke DROP COLUMN {col}")
            conn.commit()

    if current_version < 3:
        _migrate_marks_to_band_numbers(conn)


def _migrate_marks_to_band_numbers(conn) -> None:
    """
    Version 3: bestellt/angekommen enthielten bisher nur "1" (= "der
    nächste Band"). Da eine solche Markierung bei jedem "+1" entfernt
    wurde, meinte sie immer genau Bände (bis) + 1 - diese Bandnummer wird
    jetzt eingetragen. Ist "Bände (bis)" keine Zahl, bleibt der Wert stehen.
    """
    rows = conn.execute(
        "SELECT id, baende_bis, bestellt, angekommen FROM werke WHERE bestellt = '1' OR angekommen = '1'"
    ).fetchall()
    for row_id, baende_bis, bestellt, angekommen in rows:
        try:
            next_band = str(int((baende_bis or "").strip()) + 1)
        except ValueError:
            continue
        conn.execute(
            "UPDATE werke SET bestellt = ?, angekommen = ? WHERE id = ?",
            (
                next_band if bestellt == "1" else bestellt,
                next_band if angekommen == "1" else angekommen,
                row_id,
            ),
        )
    conn.commit()


def init_db():
    with closing(get_connection()) as conn:
        cols_sql = ",\n".join(f"{name} {ctype}" for name, ctype in STORED_COLUMNS)
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS werke (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {cols_sql}
            )
            """
        )
        conn.commit()

        # Fehlende Spalten bei bestehenden Datenbanken ergänzen - CREATE TABLE
        # IF NOT EXISTS ändert eine vorhandene Tabelle nicht.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(werke)").fetchall()}
        for name, ctype in STORED_COLUMNS:
            if name not in existing_cols:
                conn.execute(f"ALTER TABLE werke ADD COLUMN {name} {ctype}")
        conn.commit()

        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version < SCHEMA_VERSION:
            _apply_migrations(conn, current_version)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()


def load_all():
    """Lädt den gesamten aktuell gespeicherten Bestand als Liste von Dicts
    (inkl. 'id'). Wird beim Programmstart und nach Google-Drive-Downloads
    aufgerufen, um den Speicher-Puffer zu befüllen."""
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM werke ORDER BY titel COLLATE NOCASE").fetchall()
    return [dict(row) for row in rows]


def replace_all(entries):
    """
    Schreibt den kompletten Bestand aus dem Speicher-Puffer in die
    Datenbank (aktives Speichern). Der bisherige Inhalt wird ersetzt, alle
    Einträge bekommen dabei frische, fortlaufende IDs.

    Löschen und Neu-Schreiben laufen in einer einzigen Transaktion: Schlägt
    etwas fehl, wird alles zurückgerollt und die Ausnahme weitergereicht -
    die Datenbank behält dann ihren bisherigen Inhalt.

    Gibt den frisch aus der Datenbank geladenen Bestand zurück (mit den
    neu vergebenen IDs), damit der Puffer synchron bleibt.
    """
    cols = ", ".join(STORED_COLUMN_NAMES)
    placeholders = ", ".join("?" for _ in STORED_COLUMN_NAMES)
    rows = [[entry.get(c, "") or "" for c in STORED_COLUMN_NAMES] for entry in entries]
    with closing(get_connection()) as conn, conn:  # commit bei Erfolg, rollback bei einer Ausnahme
        conn.execute("DELETE FROM werke")
        conn.executemany(f"INSERT INTO werke ({cols}) VALUES ({placeholders})", rows)
    return load_all()


# ---------------------------------------------------------------------------
# Sicherungen & Austausch der Datenbankdatei
# ---------------------------------------------------------------------------

def backup_dir():
    """Ordner der Datenbank-Sicherungen (BACKUP/ neben der Datenbank)."""
    return DB_FILE.parent / BACKUP_DIR_NAME


def create_backup(reason: str, keep: Optional[int] = None):
    """
    Legt eine Kopie der aktuellen Datenbankdatei als
    BACKUP/manga_library_<Datum>_<Uhrzeit>_<reason>.db an und räumt danach
    alte Sicherungen weg, sodass höchstens `keep` (Standard: config.json
    "db_backup_keep") übrig bleiben.

    Kopiert wird über die Backup-Funktion von SQLite (konsistente Kopie,
    auch falls die Datei gerade geöffnet ist). Gibt den Pfad der Sicherung
    zurück, oder None, wenn noch keine Datenbankdatei existiert. Löst
    sqlite3.Error/OSError aus, wenn die Sicherung nicht angelegt werden kann.
    """
    if not DB_FILE.exists():
        return None
    if keep is None:
        keep = config.get_int("db_backup_keep", 20)

    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    # Zeitstempel vorne im Namen: das Aufräumen sortiert nach dem Namen
    path = folder / f"{BACKUP_PREFIX}{now:%Y-%m-%d_%H-%M-%S}-{now.microsecond // 1000:03d}_{reason}.db"
    with closing(sqlite3.connect(DB_FILE)) as source, closing(sqlite3.connect(path)) as target:
        source.backup(target)
    _prune_backups(keep)
    return path


def _prune_backups(keep: int) -> None:
    """Löscht die ältesten Sicherungen, sodass höchstens `keep` (mindestens
    1) übrig bleiben. Fehler beim Löschen werden ignoriert - reines
    Aufräumen, das den eigentlichen Vorgang nicht stören darf."""
    keep = max(1, keep)
    try:
        files = sorted(backup_dir().glob(BACKUP_PREFIX + "*.db"), key=lambda p: p.name)
    except OSError:
        return
    for path in files[:-keep]:
        try:
            path.unlink()
        except OSError:
            pass


def validate_database_file(path) -> None:
    """
    Prüft, ob `path` eine intakte Bibliotheks-Datenbank ist (lesbare
    SQLite-Datei, PRAGMA integrity_check = ok, Tabelle `werke` vorhanden).
    Löst ValueError mit einer für den Nutzer gedachten Meldung aus.
    """
    unchanged = "Die lokale Datenbank bleibt unverändert."
    try:
        with closing(sqlite3.connect(path)) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Die Datei ist keine gültige Datenbank ({exc}). {unchanged}") from exc
    if not check or check[0] != "ok":
        raise ValueError(f"Die Datenbank ist beschädigt ({check[0] if check else 'keine Antwort'}). {unchanged}")
    if "werke" not in tables:
        raise ValueError(f"Die Datei enthält keine Bibliotheks-Daten (Tabelle „werke“ fehlt). {unchanged}")


def replace_database_file(new_file, reason: str) -> Optional[str]:
    """
    Ersetzt die lokale Datenbankdatei durch `new_file` (z.B. einen
    Google-Drive-Download): prüft die neue Datei zuerst (siehe
    validate_database_file), sichert dann die bisherige Datenbank (siehe
    create_backup) und tauscht die Datei erst danach in einem Schritt aus
    (os.replace). Scheitert ein Schritt, bleibt die lokale Datenbank
    unverändert.

    Gibt den Pfad der Sicherung zurück (oder None, wenn es noch keine
    lokale Datenbank gab).
    """
    validate_database_file(new_file)
    backup_path = create_backup(reason)
    os.replace(new_file, DB_FILE)
    return str(backup_path) if backup_path else None

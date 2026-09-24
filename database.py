"""
database.py
Kapselt den SQLite-Zugriff der Manga/Light-Novel-Bibliothek.

Die GUI arbeitet mit einem Puffer im Speicher (Liste von Dicts); die
Datenbank wird nur beim Start gelesen (load_all) und beim aktiven Speichern
komplett neu geschrieben (replace_all). Es gibt bewusst keine Funktionen,
die einzelne Zeilen sofort in die Datenbank schreiben.
"""

import sqlite3

from paths import base_dir

DB_FILE = base_dir() / "manga_library.db"

# Schema-Versionierung über SQLites eingebautes PRAGMA user_version (ein
# einzelner Integer, direkt im Datenbank-Header gespeichert - kein
# zusätzliches Tabellen-Setup nötig). Ergänzt die bisherige Spalten-
# Migration (ALTER TABLE ADD COLUMN, siehe init_db) um einen Ort für
# künftige STRUKTURELLE Änderungen (z.B. eine Tabelle aufteilen, einen
# Fremdschlüssel ergänzen), die sich nicht mehr mit einem einfachen
# "fehlende Spalte ergänzen" abbilden lassen. Aktuell gibt es nur Version 1
# (Ausgangszustand) - siehe _apply_migrations().
SCHEMA_VERSION = 1

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
    ("voe_4", "TEXT"),
    ("voe_5", "TEXT"),
]

COLUMN_NAMES = [c[0] for c in COLUMNS]

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
    "voe_4": "VÖ +4",
    "voe_5": "VÖ +5",
}


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _apply_migrations(conn, current_version: int) -> None:
    """
    Führt alle noch ausstehenden strukturellen Schema-Migrationen aus
    (Versionen zwischen `current_version` und SCHEMA_VERSION). Aktuell gibt
    es nur Version 1 (Ausgangszustand), es ist also noch nichts
    nachzuholen - der Rahmen steht bereit für künftige strukturelle
    Änderungen, die über eine einfache Spalten-Ergänzung hinausgehen, z.B.:

        if current_version < 2:
            conn.execute("...")
    """


def init_db():
    conn = get_connection()
    cols_sql = ",\n".join(f"{name} {ctype}" for name, ctype in COLUMNS)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS werke (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {cols_sql}
        )
        """
    )
    conn.commit()

    # Migration: fehlende Spalten bei bereits bestehenden Datenbanken ergänzen,
    # falls sich COLUMNS künftig einmal erweitert. CREATE TABLE IF NOT EXISTS
    # ändert eine bereits vorhandene Tabelle nicht.
    # (Die "isbn"-Spalte für den ISBN-Abgleich wird bewusst NICHT hier verwaltet,
    # sondern eigenständig von isbn_lookup.py - sie ist kein Teil des normalen
    # Datenmodells/Puffers, da sie sich mit jedem Band ändert und beim
    # Speichern nicht dauerhaft mitgeführt werden muss.)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(werke)").fetchall()}
    for name, ctype in COLUMNS:
        if name not in existing_cols:
            conn.execute(f"ALTER TABLE werke ADD COLUMN {name} {ctype}")
    conn.commit()

    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if current_version < SCHEMA_VERSION:
        _apply_migrations(conn, current_version)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    conn.close()


def load_all():
    """Lädt den gesamten aktuell gespeicherten Bestand als Liste von Dicts
    (inkl. 'id'). Wird beim Programmstart und nach Google-Drive-Downloads
    aufgerufen, um den Speicher-Puffer zu befüllen."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM werke ORDER BY titel COLLATE NOCASE").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def replace_all(entries):
    """
    Schreibt den kompletten Bestand aus dem Speicher-Puffer in die
    Datenbank (aktives Speichern). Der bisherige Inhalt wird ersetzt, alle
    Einträge bekommen dabei frische, fortlaufende IDs.

    Gibt den frisch aus der Datenbank geladenen Bestand zurück (mit den
    neu vergebenen IDs), damit der Puffer synchron bleibt.
    """
    conn = get_connection()
    conn.execute("DELETE FROM werke")
    cols = ", ".join(COLUMN_NAMES)
    placeholders = ", ".join("?" for _ in COLUMN_NAMES)
    for entry in entries:
        conn.execute(
            f"INSERT INTO werke ({cols}) VALUES ({placeholders})",
            [entry.get(c, "") or "" for c in COLUMN_NAMES],
        )
    conn.commit()
    conn.close()
    return load_all()

"""
changelog.py
Live-Änderungsprotokoll: jede Datenänderung (Anlegen, Bearbeiten, Löschen,
"+1"-Buttons, CSV-Import, Rückgängig/Wiederholen) wird als kurze Zeile
protokolliert.

- Live-Anzeige in der Oberfläche: nur für die laufende Sitzung (wird beim
  nächsten Programmstart nicht erneut geladen).
- Datei LOG/aenderungen.log: dauerhaft, über Sitzungen hinweg. Einträge,
  die älter als 6 Monate sind, werden beim nächsten Programmstart
  automatisch nach LOG/aenderungen_archiv.log verschoben (nicht gelöscht).
"""

from datetime import datetime, timedelta

from paths import base_dir

LOG_DIR = base_dir() / "LOG"
CHANGELOG_FILE = LOG_DIR / "aenderungen.log"
ARCHIVE_FILE = LOG_DIR / "aenderungen_archiv.log"
RETENTION_DAYS = 182  # ~6 Monate

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def log_change(message: str) -> str:
    """Protokolliert eine einzelne Änderung mit Zeitstempel in die
    dauerhafte Log-Datei. Gibt die formatierte Zeile zurück (für die
    Live-Anzeige in der Oberfläche)."""
    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    line = f"[{timestamp}] {message}"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CHANGELOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # Live-Anzeige funktioniert auch, wenn die Datei nicht beschreibbar ist
    return line


def _extract_timestamp(line: str):
    if not line.startswith("["):
        return None
    end = line.find("]")
    if end == -1:
        return None
    try:
        return datetime.strptime(line[1:end], _TIMESTAMP_FORMAT)
    except ValueError:
        return None


def archive_old_entries(retention_days: int = RETENTION_DAYS) -> int:
    """
    Verschiebt Einträge, die älter als `retention_days` sind, aus der
    laufenden Log-Datei in die Archiv-Datei (angehängt, nicht überschrieben).
    Gibt die Anzahl der archivierten Zeilen zurück. Wird einmal beim
    Programmstart aufgerufen.

    Bei Lese-/Schreibproblemen (z.B. Datei von einem anderen Programm
    gesperrt, fehlende Schreibrechte im LOG-Ordner) wird 0 zurückgegeben,
    statt den Programmstart mit einer unbehandelten Exception zu verhindern
    - die Archivierung ist ein reines Aufräumen, kein kritischer Vorgang.
    """
    try:
        if not CHANGELOG_FILE.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=retention_days)
        kept, archived = [], []

        with open(CHANGELOG_FILE, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                ts = _extract_timestamp(line)
                if ts is not None and ts < cutoff:
                    archived.append(line)
                else:
                    kept.append(line)

        if not archived:
            return 0

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
            for line in archived:
                f.write(line + "\n")

        with open(CHANGELOG_FILE, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")

        return len(archived)
    except OSError:
        return 0

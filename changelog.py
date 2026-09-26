"""
changelog.py
Live-Änderungsprotokoll: jede Datenänderung (Anlegen, Bearbeiten, Löschen,
"+1"-Buttons, CSV-Import, Rückgängig/Wiederholen) wird als kurze Zeile
protokolliert.

- Live-Anzeige in der Oberfläche: nur für die laufende Sitzung (wird beim
  nächsten Programmstart nicht erneut geladen).
- Datei LOG/aenderungen.log: dauerhaft, über Sitzungen hinweg. Einträge,
  die älter als `log_retention_days` Tage sind (config.json, Standard 182
  = ca. 6 Monate), werden beim nächsten Programmstart automatisch nach
  LOG/aenderungen_archiv.log verschoben (nicht gelöscht).
- Dateien LOG/isbn_abgleich_*.log (ein ISBN-Abgleich je Datei): es bleiben
  nur die neuesten `isbn_log_keep` Dateien liegen (Standard 10), ältere
  werden gelöscht - siehe prune_isbn_logs().
- Dateien LOG/bestellung_einlesen_*.log (ein Einlesen einer Bestellung je
  Datei, siehe write_order_log()): es bleiben nur die neuesten
  `order_log_keep` Dateien liegen (Standard 10).
- Datei LOG/fehler.log: unerwartete Programmfehler mit vollständigem
  Traceback (siehe log_error(), aufgerufen vom Fehler-Handler in main.py).
"""

from datetime import datetime, timedelta

import config
from paths import base_dir

LOG_DIR = base_dir() / "LOG"
CHANGELOG_FILE = LOG_DIR / "aenderungen.log"
ARCHIVE_FILE = LOG_DIR / "aenderungen_archiv.log"
ERROR_LOG_FILE = LOG_DIR / "fehler.log"
RETENTION_DAYS = config.DEFAULTS["log_retention_days"]  # überschreibbar über config.json
ISBN_LOG_PREFIX = "isbn_abgleich_"
ISBN_LOG_PATTERN = ISBN_LOG_PREFIX + "*.log"
ORDER_LOG_PREFIX = "bestellung_einlesen_"
ORDER_LOG_PATTERN = ORDER_LOG_PREFIX + "*.log"

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


def log_error(details: str):
    """Hängt einen unerwarteten Fehler (Traceback) mit Zeitstempel an
    LOG/fehler.log an. Gibt den Pfad der Datei zurück, oder None, wenn sie
    nicht beschreibbar ist."""
    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}]\n{details.rstrip()}\n\n")
    except OSError:
        return None
    return str(ERROR_LOG_FILE)


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


def _prune_logs(pattern: str, keep: int) -> int:
    """Löscht die ältesten Dateien zu `pattern` im LOG-Ordner, sodass
    höchstens `keep` (mindestens 1) übrig bleiben. Der Dateiname enthält
    Datum und Uhrzeit, "älter" richtet sich daher nach dem Namen. Gibt die
    Anzahl gelöschter Dateien zurück; Fehler (z.B. gesperrte Datei) werden
    ignoriert - das ist reines Aufräumen und darf weder Programmstart noch
    den eigentlichen Vorgang stören."""
    keep = max(1, keep)
    deleted = 0
    try:
        files = sorted(LOG_DIR.glob(pattern), key=lambda p: p.name)
    except OSError:
        return 0
    for path in files[:-keep]:
        try:
            path.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted


def prune_isbn_logs(keep: int = None) -> int:
    """Begrenzt LOG/isbn_abgleich_*.log auf die neuesten `keep` Dateien
    (Standard: config.json "isbn_log_keep", 10)."""
    if keep is None:
        keep = config.get_int("isbn_log_keep", 10)
    return _prune_logs(ISBN_LOG_PATTERN, keep)


def prune_order_logs(keep: int = None) -> int:
    """Begrenzt LOG/bestellung_einlesen_*.log auf die neuesten `keep` Dateien
    (Standard: config.json "order_log_keep", 10)."""
    if keep is None:
        keep = config.get_int("order_log_keep", 10)
    return _prune_logs(ORDER_LOG_PATTERN, keep)


def _write_log(prefix: str, lines: list) -> str:
    """Schreibt `lines` als neue Datei LOG/<prefix><Datum>_<Uhrzeit>-<ms>.log
    und gibt den Pfad zurück. Der Name ist immer größer als alle vorhandenen
    mit demselben Präfix (das Aufräumen sortiert nach dem Namen) - auch wenn
    mehrere Vorgänge in derselben Millisekunde schreiben. Löst OSError aus,
    wenn nicht geschrieben werden kann."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    newest = max((p.name for p in LOG_DIR.glob(prefix + "*.log")), default="")
    moment = datetime.now()
    while True:
        name = f"{prefix}{moment.strftime('%Y-%m-%d_%H-%M-%S')}-{moment.microsecond // 1000:03d}.log"
        if name > newest:
            break
        moment += timedelta(milliseconds=1)
    path = LOG_DIR / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def write_order_log(lines: list) -> str:
    """Protokoll eines Einlesens einer Bestellung als eigene Datei
    LOG/bestellung_einlesen_<Datum>_<Uhrzeit>-<ms>.log; räumt danach alte
    Dateien weg (siehe prune_order_logs). Gibt den Pfad zurück."""
    path = _write_log(ORDER_LOG_PREFIX, lines)
    prune_order_logs()
    return path


def write_isbn_log(lines: list) -> str:
    """Protokoll eines ISBN-Abgleichs als eigene Datei
    LOG/isbn_abgleich_<Datum>_<Uhrzeit>-<ms>.log; räumt danach alte Dateien
    weg (siehe prune_isbn_logs). Gibt den Pfad zurück."""
    path = _write_log(ISBN_LOG_PREFIX, lines)
    prune_isbn_logs()
    return path


def archive_old_entries(retention_days: int = None) -> int:
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
    if retention_days is None:
        retention_days = config.get_int("log_retention_days", RETENTION_DAYS)
    retention_days = max(1, retention_days)
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

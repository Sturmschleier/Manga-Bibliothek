"""
config.py
Zentrale, dauerhafte Konfiguration der Anwendung. Liegt als config.json
neben der .exe bzw. neben main.py (siehe paths.base_dir()) und ist über
"Konfigurieren → Konfiguration …" direkt bearbeitbar.

Enthält Einstellungen, die über einzelne Programmstarts hinweg erhalten
bleiben sollen - siehe DEFAULTS unten für die vollständige, kommentierte
Liste. Die Datei wird sicher geschrieben (erst eine temporäre Datei, dann
Austausch in einem Schritt); eine beschädigte Datei wird vor dem nächsten
Schreiben als config.json.defekt aufbewahrt statt überschrieben.
"""

import copy
import json
import os
from typing import Optional

from paths import base_dir

CONFIG_FILE = base_dir() / "config.json"

DEFAULTS = {
    # ISBN-Abgleich: Online-Buchhändler, zu dem eine gefundene ISBN verlinkt wird
    "isbn_shop_name": "Konold",
    "isbn_shop_url_template": "https://konold.buchhandlung.de/shop/action/productDetails?id={isbn}",
    # Gewählter Anbieter für die Bestellliste (Dropdown im ISBN-Dialog, siehe shops.py):
    # "" = Standard-Buchhändler (isbn_shop_name), sonst z.B. "Thalia"
    "isbn_shop_active": "",
    # Fallback-Suche, wenn keine ISBN automatisch gefunden wurde:
    # "buchhandel.de" (Standard) oder "manga-passion"
    "isbn_fallback_provider": "buchhandel.de",
    # Protokolle (LOG-Ordner, siehe changelog.py)
    "isbn_log_keep": 10,        # so viele ISBN-Abgleich-Logdateien bleiben liegen (die ältesten werden gelöscht)
    "order_log_keep": 10,       # so viele Logdateien "Bestellung einlesen" bleiben liegen (älteste werden gelöscht)
    "log_retention_days": 182,  # Änderungsprotokoll: Einträge älter als N Tage wandern ins Archiv
    # Datenbank-Sicherungen (BACKUP-Ordner, siehe database.create_backup): vor
    # jedem Speichern und vor einem Google-Drive-Download
    "db_backup_keep": 20,       # so viele Sicherungen bleiben liegen (die ältesten werden gelöscht)
    # Postfach-Abruf von Bestellbestätigungen (IMAP, siehe mail_fetch.py).
    # Das Passwort steht bewusst NICHT hier, sondern (optional) in den
    # Windows-Anmeldeinformationen bzw. wird bei Bedarf abgefragt.
    "mail_imap_host": "",
    "mail_imap_port": 993,
    "mail_imap_security": "ssl",       # "ssl" (Port 993) oder "starttls" (Port 143)
    "mail_imap_user": "",
    "mail_folder": "INBOX",
    "mail_filter_sender": "konold",    # Absender enthält (leer = egal)
    "mail_filter_subject": "Bestellung",  # Betreff enthält (leer = egal)
    "mail_days_back": 90,
    "mail_max_messages": 30,
    # Oberfläche
    "follow_selection_after_edit": True,
    "sidebar_width_fraction": 0.15,
    # Statistik: Titel mit VÖ +1 = "Gestoppt" aus Summen-/Bilanz-
    # Berechnungen (Statistik-Box, Gesamt/Gelesen/Offen je Typ) ausschließen
    "exclude_gestoppt_from_stats": False,
    # CSV-Export: Trennzeichen - ";" öffnet sich in Excel mit deutschen
    # Einstellungen direkt in Spalten ("," landet dort alles in Spalte A)
    "csv_delimiter": ";",
    # Farbcodierung je Spalten-Kategorie einzeln (de)aktivierbar - auch
    # über "Konfigurieren → Farben". Bei deaktivierter Kategorie wird
    # stattdessen die normale Zebra-Streifung verwendet.
    "colors_enabled": {
        "voe1": True,             # VÖ +1: Beendet/TBA/Gestoppt/NA
        "komplett_beendet": True,  # Komplett/Beendet: Ja/Nein
        "verlag": True,            # automatische Farbe je Verlag
        "bestellt": True,          # Titel hellblau: nächster Band bestellt
        "angekommen": True,        # Titel mit rotem Balken: Band abholbereit
    },
}


# Zulässige Werte für Einstellungen mit fester Auswahl (siehe validate)
ALLOWED_VALUES = {
    "isbn_fallback_provider": ("buchhandel.de", "manga-passion"),
    "mail_imap_security": ("ssl", "starttls"),
    "csv_delimiter": (";", ",", "\t"),
}


def _read_file():
    """Liest config.json: (Inhalt oder None, Fehlermeldung oder None).
    Eine fehlende Datei ist kein Fehler."""
    if not CONFIG_FILE.exists():
        return None, None
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            stored = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"kein gültiges JSON ({exc})"
    except OSError as exc:
        return None, f"nicht lesbar ({exc})"
    if not isinstance(stored, dict):
        return None, "kein JSON-Objekt"
    return stored, None


def problem() -> Optional[str]:
    """Beschreibung, falls config.json existiert, aber unbrauchbar ist -
    dann gelten die Standardwerte (siehe load). Sonst None."""
    return _read_file()[1]


def load() -> dict:
    """
    Lädt die Konfiguration. Fehlende Schlüssel (z.B. nach einem Update mit
    neuen Einstellungen) werden automatisch mit den Standardwerten ergänzt,
    eine fehlende oder kaputte Datei führt nicht zum Absturz - dann werden
    einfach die Standardwerte verwendet (siehe problem()).
    """
    cfg = copy.deepcopy(DEFAULTS)
    stored, _error = _read_file()
    if stored:
        cfg.update(stored)
    return cfg


def save(cfg: dict) -> None:
    """Schreibt die komplette Konfiguration in die Datei - erst in eine
    temporäre Datei, dann Austausch in einem Schritt (os.replace), damit ein
    Absturz beim Schreiben keine halbe Datei hinterlässt. Eine vorhandene,
    aber beschädigte config.json wird vorher als config.json.defekt
    aufbewahrt, statt verloren zu gehen."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if problem():
        os.replace(CONFIG_FILE, CONFIG_FILE.with_name(CONFIG_FILE.name + ".defekt"))
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, CONFIG_FILE)


def ensure_file_exists() -> None:
    """Legt config.json mit den Standardwerten an, falls sie noch nicht
    existiert - damit der Bearbeiten-Dialog von Anfang an etwas Sinnvolles
    zum Anzeigen/Bearbeiten hat."""
    if not CONFIG_FILE.exists():
        save(copy.deepcopy(DEFAULTS))


def validate(cfg: dict) -> list[str]:
    """
    Prüft die bekannten Einstellungen auf den richtigen Typ und zulässige
    Werte (unbekannte Schlüssel bleiben erlaubt). Gibt verständliche
    Fehlermeldungen zurück, leere Liste = in Ordnung.
    """
    problems = []
    type_names = {
        bool: "true oder false", int: "eine ganze Zahl", float: "eine Zahl", str: "ein Text in Anführungszeichen",
    }
    for key, default in DEFAULTS.items():
        if key not in cfg:
            continue
        value = cfg[key]
        if isinstance(default, dict):
            if not isinstance(value, dict):
                problems.append(f"„{key}“ muss ein Objekt {{...}} sein.")
                continue
            for sub_key, sub_value in value.items():
                if sub_key in default and not isinstance(sub_value, type(default[sub_key])):
                    problems.append(f"„{key}“ → „{sub_key}“ muss {type_names[type(default[sub_key])]} sein.")
            continue
        expected = type(default)
        ok = isinstance(value, expected) and not (expected is not bool and isinstance(value, bool))
        if expected is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not ok:
            problems.append(f"„{key}“ muss {type_names[expected]} sein (ist: {json.dumps(value, ensure_ascii=False)}).")
        elif key in ALLOWED_VALUES and value not in ALLOWED_VALUES[key]:
            allowed = ", ".join(json.dumps(v) for v in ALLOWED_VALUES[key])
            problems.append(f"„{key}“ muss einer dieser Werte sein: {allowed}.")
    template = cfg.get("isbn_shop_url_template")
    if isinstance(template, str) and "{isbn}" not in template:
        problems.append("„isbn_shop_url_template“ muss den Platzhalter {isbn} enthalten.")
    return problems


def get(key: str, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def get_float(key: str, default: Optional[float] = None) -> float:
    """
    Wie `get()`, aber typsicher für Zahlenwerte: liefert immer ein `float`
    zurück. Enthält config.json für `key` einen nicht-numerischen Wert
    (z.B. versehentlich als Text "0.15" statt als Zahl, oder Unsinn wie
    "abc" nach einer manuellen Bearbeitung), wird der Standardwert
    verwendet statt einer Exception - ein kaputter Konfigurationswert darf
    das Programm nicht am Starten hindern.
    """
    if default is None:
        default = DEFAULTS.get(key, 0.0)
    value = get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_int(key: str, default: Optional[int] = None) -> int:
    """Wie `get()`, aber typsicher für ganze Zahlen: liefert immer ein `int`
    (bei Unsinn in der Datei den Standardwert statt einer Exception)."""
    if default is None:
        default = DEFAULTS.get(key, 0)
    try:
        return int(get(key, default))
    except (TypeError, ValueError, OverflowError):
        return default


def get_bool(key: str, default: Optional[bool] = None) -> bool:
    """Wie `get()`, aber typsicher für Ja/Nein-Werte: true/false, aber auch
    von Hand eingetragene Texte wie "false" oder "ja" werden richtig
    verstanden (der Text "false" wäre in Python sonst wahr). Bei Unsinn
    gilt der Standardwert."""
    if default is None:
        default = bool(DEFAULTS.get(key, False))
    value = get(key, default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in ("true", "1", "ja", "yes", "an", "on"):
        return True
    if text in ("false", "0", "nein", "no", "aus", "off"):
        return False
    return default


def get_dict(key: str, default: Optional[dict] = None) -> dict:
    """Wie `get()`, aber typsicher für Dict-Werte (z.B. "colors_enabled").
    Ist der gespeicherte Wert kein Dict, wird der Standardwert verwendet."""
    if default is None:
        default = DEFAULTS.get(key, {})
    value = get(key, default)
    return dict(value) if isinstance(value, dict) else dict(default)


def set_value(key: str, value) -> None:
    """Ändert einen einzelnen Wert und speichert sofort dauerhaft."""
    cfg = load()
    cfg[key] = value
    save(cfg)

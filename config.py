"""
config.py
Zentrale, dauerhafte Konfiguration der Anwendung. Liegt als config.json
neben der .exe bzw. neben main.py (siehe paths.base_dir()) und wird über
den Button "⚙ Konfiguration" in der Oberfläche direkt bearbeitbar gemacht.

Enthält Einstellungen, die über einzelne Programmstarts hinweg erhalten
bleiben sollen: den bevorzugten Online-Buchhändler und Fallback-Anbieter
für ISBN-Links, ob die Tabelle nach dem Bearbeiten automatisch zur
geänderten Zeile springen soll, ob "Gestoppt"-Titel aus Berechnungen
ausgeschlossen werden, die Farbcodierung je Kategorie, sowie den
Startanteil der Seitenleiste an der Fensterbreite. Siehe DEFAULTS unten
für die vollständige, kommentierte Liste.
"""

import json

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
    "log_retention_days": 182,  # Änderungsprotokoll: Einträge älter als N Tage wandern ins Archiv
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
    # Farbcodierung je Spalten-Kategorie einzeln (de)aktivierbar - auch
    # direkt über den "🎨 Farben"-Menü-Button in der Werkzeugleiste
    # erreichbar, nicht nur über diese Datei. Bei deaktivierter Kategorie
    # wird stattdessen die normale Zebra-Streifung verwendet.
    "colors_enabled": {
        "voe1": True,             # VÖ +1: Beendet/TBA/Gestoppt/NA
        "komplett_beendet": True,  # Komplett/Beendet: Ja/Nein
        "verlag": True,            # automatische Farbe je Verlag
        "bestellt": True,          # Titel hellblau: nächster Band bestellt
        "angekommen": True,        # Titel mit rotem Balken: Band abholbereit
    },
}


def load() -> dict:
    """
    Lädt die Konfiguration. Fehlende Schlüssel (z.B. nach einem Update mit
    neuen Einstellungen) werden automatisch mit den Standardwerten ergänzt,
    eine fehlende oder kaputte Datei führt nicht zum Absturz - dann werden
    einfach die Standardwerte verwendet.
    """
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                cfg.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict) -> None:
    """Schreibt die komplette Konfiguration in die Datei."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False, sort_keys=True)


def ensure_file_exists() -> None:
    """Legt config.json mit den Standardwerten an, falls sie noch nicht
    existiert - damit der Bearbeiten-Dialog von Anfang an etwas Sinnvolles
    zum Anzeigen/Bearbeiten hat."""
    if not CONFIG_FILE.exists():
        save(dict(DEFAULTS))


def get(key: str, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def get_float(key: str, default: float = None) -> float:
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


def get_int(key: str, default: int = None) -> int:
    """Wie `get()`, aber typsicher für ganze Zahlen: liefert immer ein `int`
    (bei Unsinn in der Datei den Standardwert statt einer Exception)."""
    if default is None:
        default = DEFAULTS.get(key, 0)
    try:
        return int(get(key, default))
    except (TypeError, ValueError, OverflowError):
        return default


def get_dict(key: str, default: dict = None) -> dict:
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

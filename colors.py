"""
colors.py
Erzeugt die Farben für die Tabellenansicht:

- Jeder Verlag bekommt automatisch eine eigene, stabile Farbe (per Hash aus
  dem Namen abgeleitet) – neue Verlage bekommen ohne weiteres Zutun
  automatisch eine neue, bisher ungenutzte Farbe aus dem Farbkreis.
- Die Spalte "VÖ +1" wird nach Status eingefärbt (Beendet/TBA/Gestoppt).
- Jede zweite Zeile wird leicht grau hinterlegt (Zebra-Streifen).
"""

import colorsys
import hashlib

# Helle, aber gut lesbare Statusfarben für die Spalte "VÖ +1"
VOE1_STATUS_COLORS = {
    "beendet": "#C8F0C0",     # helles Grün
    "tba": "#FFD9A0",         # helles Orange
    "gestoppt": "#FFB3B3",    # helles Rot
    "na": "#F5B3E0",          # Pink
}

# Komplett/Beendet: Ja = gleiches Grün wie VÖ+1 "Beendet", Nein = gleiches
# Rot wie VÖ+1 "Gestoppt"
JA_NEIN_COLORS = {
    "ja": VOE1_STATUS_COLORS["beendet"],
    "nein": VOE1_STATUS_COLORS["gestoppt"],
}

# Zebra-Streifen für ungerade/gerade Zeilen
ZEBRA_EVEN = "#FFFFFF"
ZEBRA_ODD = "#EDEDED"

DEFAULT_TEXT_COLOR = "#1a1a1a"


def voe1_color(value: str):
    """Liefert die Hintergrundfarbe für einen VÖ+1-Wert, falls dieser einem
    der bekannten Status entspricht, sonst None (=> normale Zebra-Farbe)."""
    if not value:
        return None
    return VOE1_STATUS_COLORS.get(value.strip().lower())


def verlag_color(verlag: str, saturation: float = 0.38, brightness: float = 0.95):
    """
    Leitet aus dem Verlagsnamen deterministisch eine helle Pastellfarbe ab.
    Gleicher Name -> immer gleiche Farbe. Verschiedene Namen verteilen sich
    automatisch über den gesamten Farbkreis, sodass neue Verlage automatisch
    eine neue, gut unterscheidbare Farbe erhalten.
    """
    if not verlag:
        return None
    digest = hashlib.md5(verlag.strip().lower().encode("utf-8")).hexdigest()
    hue = (int(digest, 16) % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, brightness)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def ja_nein_color(value: str):
    """Liefert die Hintergrundfarbe für Ja/Nein-Spalten (Komplett, Beendet)."""
    if not value:
        return None
    return JA_NEIN_COLORS.get(value.strip().lower())


def zebra_color(row_index: int):
    return ZEBRA_EVEN if row_index % 2 == 0 else ZEBRA_ODD


def cell_background(column: str, value: str, row_index: int, enabled: dict = None):
    """
    Bestimmt die Hintergrundfarbe für eine einzelne Zelle.

    `enabled` ist das optionale "colors_enabled"-Dict aus config.json
    ({"voe1": bool, "komplett_beendet": bool, "verlag": bool}) - fehlt ein
    Schlüssel oder wird `enabled` gar nicht übergeben, gilt die jeweilige
    Kategorie als aktiv (Standardverhalten unverändert). Ist eine Kategorie
    deaktiviert, wird stattdessen die normale Zebra-Farbe verwendet.
    """
    enabled = enabled or {}
    if column == "voe_1" and enabled.get("voe1", True):
        color = voe1_color(value)
        if color:
            return color
    elif column == "verlag" and enabled.get("verlag", True):
        color = verlag_color(value)
        if color:
            return color
    elif column in ("komplett", "beendet") and enabled.get("komplett_beendet", True):
        color = ja_nein_color(value)
        if color:
            return color
    return zebra_color(row_index)

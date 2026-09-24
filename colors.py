"""
colors.py
Erzeugt die Farben für die Tabellenansicht:

- Jeder Verlag bekommt automatisch eine eigene Farbe aus einer festen,
  gut unterscheidbaren Palette – neue Verlage bekommen ohne weiteres Zutun
  eine bisher ungenutzte Farbe (bis die Palette ausgeschöpft ist).
- Die Spalte "VÖ +1" wird nach Status eingefärbt (Beendet/TBA/Gestoppt).
- Jede zweite Zeile wird leicht grau hinterlegt (Zebra-Streifen).
"""

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


# Feste Palette gut unterscheidbarer Pastellfarben für Verlage. Per
# Farbabstand (CIE-Lab) so ausgewählt, dass je zwei Farben möglichst weit
# auseinanderliegen und der dunkle Text lesbar bleibt; die Reihenfolge ist
# absteigend nach "Unterscheidbarkeit", die ersten Einträge sind also die
# kontrastreichsten.
VERLAG_PALETTE = [
    "#69FA69", "#E7B4FA", "#EDB664", "#69FAFA", "#B0DB7F", "#91C9FA",
    "#69FAB6", "#FACBB4", "#EDED64", "#EDE9AB", "#9EDBBF", "#B6FA69",
    "#B4ECFA", "#5CDB76", "#B4B9FA", "#5CDBB9", "#64D2ED", "#A6FA91",
    "#E7ED8A", "#EDD264", "#B9DB5C", "#FAAD91", "#7FDB92", "#7EDB5C",
]

# Zuordnung Verlag (kleingeschrieben) -> Farbe, siehe set_verlag_universe()
_verlag_colors = {}


def _hash_slot(verlag: str) -> int:
    digest = hashlib.md5(verlag.strip().lower().encode("utf-8")).hexdigest()
    return int(digest, 16) % len(VERLAG_PALETTE)


def set_verlag_universe(verlage):
    """
    Weist allen aktuell vorkommenden Verlagen je eine eigene Palettenfarbe zu.

    Jeder Verlag bewirbt sich zuerst um den aus seinem Namen abgeleiteten
    Palettenplatz (dadurch bleibt die Farbe stabil, solange sich nichts
    überschneidet); ist der Platz schon vergeben, rückt er auf den nächsten
    freien vor. Es wird in alphabetischer Reihenfolge vergeben, das Ergebnis
    hängt also nicht von der Anzeigereihenfolge ab. Erst bei mehr Verlagen
    als Palettenfarben müssen Farben mehrfach vergeben werden.
    """
    names = sorted({v.strip().lower() for v in verlage if v and v.strip()})
    size = len(VERLAG_PALETTE)
    used = set()
    mapping = {}
    for name in names:
        slot = _hash_slot(name)
        if len(used) < size:
            while slot in used:
                slot = (slot + 1) % size
            used.add(slot)
        mapping[name] = VERLAG_PALETTE[slot]
    _verlag_colors.clear()
    _verlag_colors.update(mapping)


def verlag_color(verlag: str):
    """
    Liefert die Farbe eines Verlags. Gleicher Name -> gleiche Farbe; sind
    die vorkommenden Verlage per set_verlag_universe() bekannt, sind die
    Farben paarweise verschieden. Unbekannte Namen erhalten die Farbe ihres
    Hash-Platzes.
    """
    if not verlag or not verlag.strip():
        return None
    key = verlag.strip().lower()
    return _verlag_colors.get(key) or VERLAG_PALETTE[_hash_slot(key)]


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

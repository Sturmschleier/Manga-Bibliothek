"""
logic.py
Reine Verarbeitungslogik, die ausschließlich auf einem einzelnen
Puffer-Eintrag (Dict) arbeitet – ohne Datenbankzugriff. So bleiben
Änderungen im Speicher, bis sie aktiv gespeichert werden.
"""

import re
from typing import Optional, Union

import sorting
from database import VOE_COLUMNS

# Sentinel-Rückgabewert von increment_gelesen(), siehe dort. Als benannte
# Konstante statt eines an mehreren Stellen wiederholten "Magic String".
EXCEEDS = "exceeds"

# Bestellt-/Angekommen-Markierungen (siehe order_mail.FLAG_FIELD): Wert ist
# die Bandnummer, für die die Markierung gilt.
MARK_FIELDS = ("bestellt", "angekommen")


def parse_int(value) -> Optional[int]:
    """Ganze Zahl aus einem Feldwert (Text wie "12", " 7 "), sonst None -
    für "Bände (bis)", "Gelesen bis" und die Markierungen."""
    try:
        return int(str(value if value is not None else "").strip())
    except ValueError:
        return None


# Sieht aus wie ein Datum (nur Ziffern und Punkte), z.B. "15.13.2026"
_DATE_LIKE_RE = re.compile(r"^[\d.]+$")
_DATE_FIELDS = ("zugang", *VOE_COLUMNS)


def validate_entry(values: dict, other_titles=()) -> list[str]:
    """
    Prüft die Werte aus dem Bearbeiten-Formular und gibt verständliche
    Fehlermeldungen zurück (leere Liste = alles in Ordnung):
      - Titel ist Pflicht und darf nicht schon vorkommen (`other_titles`:
        klein geschriebene Titel aller ANDEREN Einträge) - doppelte Titel
        würden ISBN-Zwischenspeicher und Bestellzuordnung durcheinanderbringen
      - "Bände (bis)" und "Gelesen bis" sind leer oder ganze Zahlen,
        "Gelesen bis" nicht größer als "Bände (bis)"
      - Datumswerte (Zugang, VÖ) sind TT.MM.JJJJ oder MM.JJJJ; Freitext wie
        "TBA" oder "Band 17 11.06.2025" bleibt erlaubt
    """
    problems = []
    titel = (values.get("titel") or "").strip()
    if not titel:
        problems.append("Bitte einen Titel angeben.")
    elif titel.casefold() in other_titles:
        problems.append(f"Den Titel „{titel}“ gibt es bereits.")

    numbers = {}
    for key, label in (("baende_bis", "Bände (bis)"), ("gelesen_bis", "Gelesen bis")):
        raw = (values.get(key) or "").strip()
        numbers[key] = parse_int(raw)
        if raw and numbers[key] is None:
            problems.append(f"„{label}“ muss eine ganze Zahl sein (ist: „{raw}“).")
    if (numbers["baende_bis"] is not None and numbers["gelesen_bis"] is not None
            and numbers["gelesen_bis"] > numbers["baende_bis"]):
        problems.append("„Gelesen bis“ kann nicht größer als „Bände (bis)“ sein.")

    for key in _DATE_FIELDS:
        raw = (values.get(key) or "").strip()
        if raw and _DATE_LIKE_RE.match(raw) and sorting.parse_date(raw) is None:
            problems.append(f"„{raw}“ ist kein gültiges Datum (TT.MM.JJJJ oder MM.JJJJ).")
    return problems


def clear_fulfilled_marks(entry: dict) -> bool:
    """
    Entfernt Bestellt-/Angekommen-Markierungen, deren Band inzwischen im
    Bestand ist ("Bände (bis)" >= markierter Band) - z.B. nach "+1" oder
    nach dem Hochsetzen der Bände im Bearbeiten-Formular. Ist Band 14
    bestellt und "Bände (bis)" steigt nur auf 13, bleibt die Markierung.

    Lässt sich eine der beiden Zahlen nicht lesen, bleibt die Markierung
    unverändert. Verändert `entry` in place; gibt True zurück, wenn
    mindestens eine Markierung entfernt wurde.
    """
    owned = parse_int(entry.get("baende_bis"))
    if owned is None:
        return False
    changed = False
    for field_name in MARK_FIELDS:
        band = parse_int(entry.get(field_name))
        if band is not None and owned >= band:
            entry[field_name] = ""
            changed = True
    return changed


def increment_baende(entry: dict) -> Optional[int]:
    """
    Erhöht "Bände (bis)" um 1 und rückt die VÖ-Termine eine Position nach
    vorne (VÖ+2 -> VÖ+1, VÖ+3 -> VÖ+2, usw.), da der bisherige VÖ+1-Termin
    durch den neuen Band eingelöst wurde. Sind danach keine Termine mehr
    vorhanden, wird in VÖ+1 "NA" eingetragen.

    Ausnahme: Steht in VÖ+1 der Text "Fortlaufend" (die Reihe erscheint
    ohne festen, bandweise weiterrückenden Zeitplan), wird NICHTS
    verschoben - VÖ+1 bleibt unverändert auf "Fortlaufend" stehen, auch
    VÖ+2 und VÖ+3 bleiben unangetastet.

    Verändert `entry` in place. Gibt den neuen Bände-Wert zurück, oder
    None, falls "Bände (bis)" keine gültige Zahl enthält (entry bleibt in
    diesem Fall unverändert).
    """
    current = parse_int(entry.get("baende_bis") or "0")   # leer zählt als 0
    if current is None:
        return None
    new_baende = current + 1

    entry["baende_bis"] = str(new_baende)

    if (entry.get("voe_1") or "").strip().lower() != "fortlaufend":
        voe_values = [entry.get(key) or "" for key in VOE_COLUMNS]
        shifted = [*voe_values[1:], ""]
        if not any(v.strip() for v in shifted):
            shifted[0] = "NA"
        for key, value in zip(VOE_COLUMNS, shifted):
            entry[key] = value

    # Alte Datenbanken können noch eine "isbn"-Spalte in `werke` haben (heute
    # steht die ISBN in isbn_cache): sie gilt nur für den bisherigen Band.
    if "isbn" in entry:
        entry["isbn"] = ""

    return new_baende


def increment_gelesen(entry: dict) -> Union[int, str, None]:
    """
    Erhöht "Gelesen bis" um 1 (beeinflusst nur dieses eine Feld).
    Verändert `entry` bei Erfolg in place.

    Rückgabe:
      - int: der neue Wert, wenn erfolgreich erhöht.
      - None: "Gelesen bis" enthält keine gültige Zahl.
      - logic.EXCEEDS ("exceeds"): der neue Wert würde "Bände (bis)"
        übersteigen - man kann nicht mehr Bände gelesen haben, als man
        besitzt. `entry` bleibt in diesem Fall unverändert. Ist
        "Bände (bis)" selbst keine gültige Zahl (oder leer), wird nicht
        geprüft (kein Vergleich möglich).
    """
    current = parse_int(entry.get("gelesen_bis") or "0")   # leer zählt als 0
    if current is None:
        return None
    new_value = current + 1

    baende_value = parse_int(entry.get("baende_bis"))
    if baende_value is not None and new_value > baende_value:
        return EXCEEDS

    entry["gelesen_bis"] = str(new_value)
    return new_value

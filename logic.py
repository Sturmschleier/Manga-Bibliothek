"""
logic.py
Reine Verarbeitungslogik, die ausschließlich auf einem einzelnen
Puffer-Eintrag (Dict) arbeitet – ohne Datenbankzugriff. So bleiben
Änderungen im Speicher, bis sie aktiv gespeichert werden.
"""

from typing import Optional, Union

# Sentinel-Rückgabewert von increment_gelesen(), siehe dort. Als benannte
# Konstante statt eines an mehreren Stellen wiederholten "Magic String".
EXCEEDS = "exceeds"


def increment_baende(entry: dict) -> Optional[int]:
    """
    Erhöht "Bände (bis)" um 1 und rückt die VÖ-Termine eine Position nach
    vorne (VÖ+2 -> VÖ+1, VÖ+3 -> VÖ+2, usw.), da der bisherige VÖ+1-Termin
    durch den neuen Band eingelöst wurde. Sind danach keine Termine mehr
    vorhanden, wird in VÖ+1 "NA" eingetragen.

    Ausnahme: Steht in VÖ+1 der Text "Fortlaufend" (die Reihe erscheint
    ohne festen, bandweise weiterrückenden Zeitplan), wird NICHTS
    verschoben - VÖ+1 bleibt unverändert auf "Fortlaufend" stehen, auch
    VÖ+2 … VÖ+5 bleiben unangetastet.

    Verändert `entry` in place. Gibt den neuen Bände-Wert zurück, oder
    None, falls "Bände (bis)" keine gültige Zahl enthält (entry bleibt in
    diesem Fall unverändert).
    """
    try:
        new_baende = int((entry.get("baende_bis") or "0").strip()) + 1
    except ValueError:
        return None

    entry["baende_bis"] = str(new_baende)

    if (entry.get("voe_1") or "").strip().lower() != "fortlaufend":
        voe_values = [entry.get(f"voe_{i}") or "" for i in range(1, 6)]
        shifted = voe_values[1:] + [""]
        if not any(v.strip() for v in shifted):
            shifted[0] = "NA"
        for i in range(5):
            entry[f"voe_{i + 1}"] = shifted[i]

    # Altlasten-Kompatibilität: frühere Programmversionen legten eine
    # transiente "isbn"-Spalte direkt in `werke` an und der Puffer konnte
    # sie dadurch (via SELECT *) enthalten. Seit der isbn_cache-Tabelle
    # (siehe isbn_lookup.py) betrifft das nur noch Alt-Datenbanken - ist
    # der Schlüssel trotzdem vorhanden, wird er hier weiterhin geleert,
    # da er sich ohnehin nur auf den alten Band-Stand bezogen hätte.
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
    try:
        new_value = int((entry.get("gelesen_bis") or "0").strip()) + 1
    except ValueError:
        return None

    baende_raw = (entry.get("baende_bis") or "").strip()
    if baende_raw:
        try:
            baende_value = int(baende_raw)
        except ValueError:
            baende_value = None
        if baende_value is not None and new_value > baende_value:
            return EXCEEDS

    entry["gelesen_bis"] = str(new_value)
    return new_value

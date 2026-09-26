"""
order_mail.py
Liest die Bestellbestätigung eines Online-Buchhändlers aus einer E-Mail-Datei
(.eml) und ordnet die bestellten Artikel den Einträgen der Bibliothek zu.

Die E-Mail wird nur gelesen und im Speicher ausgewertet - weder die Datei
noch Teile daraus (Adresse, Bestellnummer, Preise ...) werden gespeichert.
Übernommen wird ausschließlich die Markierung "bestellt" am jeweiligen
Bibliotheks-Eintrag.

Erkannt wird das Layout der Konold-Bestellbestätigung: eine HTML-Tabelle mit
je Artikel einer Zeile "Artikelname | Anzahl | Preis EUR". Andere Shops mit
ähnlicher Tabellenstruktur funktionieren in der Regel ebenfalls.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from logic import parse_int

_PRICE_RE = re.compile(r"^\d[\d.,]*\s*(EUR|€)$", re.IGNORECASE)
# "…04-EAN:9783755507260" am Ende des Artikelnamens
_EAN_SUFFIX_RE = re.compile(r"[\s-]*EAN\s*:?\s*\d+\s*$", re.IGNORECASE)

KIND_ORDER = "bestellung"    # Bestellbestätigung: Artikel wurden bestellt
KIND_PICKUP = "abholung"     # Abhol-Benachrichtigung: Artikel sind angekommen

# Feld des Eintrags, in dem die jeweilige Markierung steht. Gespeichert wird
# die (höchste) Bandnummer, für die sie gilt - z.B. bestellt = "14". Sie
# entfällt erst, wenn "Bände (bis)" diesen Band erreicht (siehe
# logic.clear_fulfilled_marks), nicht schon beim nächsten "+1".
FLAG_FIELD = {KIND_ORDER: "bestellt", KIND_PICKUP: "angekommen"}
_BAND_RE = re.compile(r"^(?:band\s+|bd\s+|vol\s+|volume\s+)?(\d+)(?=\s|$)")


@dataclass
class OrderItem:
    """Ein bestellter Artikel, wie er in der E-Mail steht."""
    name: str
    menge: int = 1
    kind: str = KIND_ORDER


class _RowCollector(HTMLParser):
    """Sammelt je <tr> die Texte der direkten Zellen (<td>/<th>)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self.rows.append([])  # Tabellenende als Trennmarke (verschachtelte Tabellen verlieren sonst ihre Zeilengrenzen)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_eml(path: str) -> list[OrderItem]:
    """Liest die bestellten Artikel aus einer .eml-Datei. Löst ValueError
    aus, wenn die Datei keine auswertbare Bestellung enthält."""
    with open(path, "rb") as f:
        return parse_message_bytes(f.read())


def parse_message_bytes(raw: bytes) -> list[OrderItem]:
    """Wie parse_eml, aber für eine E-Mail, die bereits als Bytes im
    Speicher vorliegt (z.B. per IMAP abgerufen, siehe mail_fetch.py).

    Löst bei jeder nicht auswertbaren Mail ValueError aus - auch bei
    technisch kaputten oder ungewöhnlichen Mails (z.B. unbekannter
    Zeichensatz), damit eine einzelne solche Mail nicht den ganzen Import
    mehrerer Mails abbricht."""
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        body = message.get_body(preferencelist=("html",))
        if body is None:
            raise ValueError("Die E-Mail enthält keinen HTML-Teil mit einer Artikelliste.")
        return parse_html(body.get_content())
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - fremde Mail-Inhalte: jeder Fehler = "nicht lesbar"
        raise ValueError(f"Die E-Mail konnte nicht gelesen werden ({type(exc).__name__}: {exc}).") from exc


def _clean_name(name: str) -> str:
    return _EAN_SUFFIX_RE.sub("", name).strip()


def parse_html(html_text: str) -> list[OrderItem]:
    """Liest die Artikel aus dem HTML einer Bestell-Mail. Die Art der Mail
    ergibt sich aus der Tabellenstruktur (nicht aus Textbausteinen):
      - Bestellbestätigung: Zeilen "Name | Anzahl | Preis EUR"  (KIND_ORDER)
      - Abhol-Benachrichtigung ("… abholbereit"): keine Preise, stattdessen
        eine Tabelle mit den Spalten "Artikel | Menge"  (KIND_PICKUP)
    """
    collector = _RowCollector()
    collector.feed(html_text)
    collector.close()

    ordered, picked_up = [], []
    in_pickup_table = False
    for cells in collector.rows:
        cells = [c for c in cells if c != ""]
        # Bestellzeile: Name | Anzahl (ganze Zahl) | Preis (z.B. "8,50 EUR")
        if len(cells) >= 3 and cells[1].isdigit() and _PRICE_RE.match(cells[2]):
            ordered.append(OrderItem(_clean_name(cells[0]), int(cells[1]), KIND_ORDER))
            continue
        # Abhol-Mail: Kopfzeile "Artikel | Menge", danach je Artikel "Name | Menge"
        if [c.casefold() for c in cells[:2]] == ["artikel", "menge"] and len(cells) == 2:
            in_pickup_table = True
            continue
        if in_pickup_table:
            if len(cells) == 2 and cells[1].isdigit():
                picked_up.append(OrderItem(_clean_name(cells[0]), int(cells[1]), KIND_PICKUP))
                continue
            in_pickup_table = False

    items = ordered or picked_up
    if not items:
        raise ValueError(
            "In der E-Mail wurde keine Artikelliste gefunden "
            "(Bestellbestätigung: Name, Anzahl, Preis - Abholmail: Artikel, Menge)."
        )
    return items


def _normalize(text: str) -> str:
    """Vergleichsform: Kleinbuchstaben, alle Nicht-Buchstaben/-Ziffern
    (Bindestriche, Satzzeichen, typografische Zeichen) werden zu einem
    Leerzeichen zusammengefasst."""
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


@dataclass
class Match:
    item: OrderItem
    entry: dict
    band: int


def match_items(items, entries):
    """
    Ordnet Artikel den Bibliotheks-Einträgen zu. Ein Artikel passt zu einem
    Eintrag, wenn sein Name mit dem Titel des Eintrags beginnt und danach
    die Bandnummer folgt - z.B. "Sanda - Band 12" oder "Fabiniku 14" zu
    "Sanda" bzw. "Fabiniku"; Zusätze nach der Nummer ("… im Sammelschuber")
    stören nicht. Steht zwischen Titel und Nummer noch ein Zusatz
    ("Togen Anki - Teufelsblut 23"), zählt das nur, wenn die Nummer genau
    "Bände (bis)" + 1 ist. Bei mehreren möglichen Titeln gewinnt der längste.

    Ist "Bände (bis)" des Eintrags eine Zahl und die bestellte Bandnummer
    nicht größer, gilt der Band als bereits vorhanden und wird nicht
    markiert.

    Gibt (matches, already_owned, unmatched) zurück:
      - matches:       Liste von Match - je Eintrag und Art (bestellt/
                       abholbereit) nur einer, und zwar mit dem höchsten
                       Band (z.B. Band 13 und 14 in derselben Bestellung
                       -> Band 14)
      - already_owned: Liste von Match (Band schon im Bestand)
      - unmatched:     Liste von OrderItem ohne passenden Eintrag
    """
    candidates = []
    for entry in entries:
        key = _normalize(entry.get("titel") or "")
        if key:
            candidates.append((key, entry))
    candidates.sort(key=lambda c: len(c[0]), reverse=True)

    matches, already_owned, unmatched = [], [], []
    position = {}  # (id(entry), kind) -> Index in matches
    for item in items:
        name = _normalize(item.name)
        found = None
        for key, entry in candidates:
            if not name.startswith(key + " "):
                continue
            rest = name[len(key):].strip()
            band_match = _BAND_RE.match(rest)
            if band_match:
                found = Match(item, entry, int(band_match.group(1)))
                break
            # Lockerer Treffer: Untertitel/Zusatz zwischen Titel und Nummer
            # ("Togen Anki - Teufelsblut 23", "... Light Novel 10"). Nur
            # akzeptiert, wenn die Nummer genau der nächste Band (Bände (bis)
            # + 1) ist - sonst zu unsicher.
            owned = parse_int(entry.get("baende_bis"))
            if owned is not None and str(owned + 1) in rest.split():
                found = Match(item, entry, owned + 1)
                break
        if found is None:
            unmatched.append(item)
            continue

        owned = parse_int(found.entry.get("baende_bis"))
        key = (id(found.entry), item.kind)
        if owned is not None and found.band <= owned:
            already_owned.append(found)
        elif key not in position:
            position[key] = len(matches)
            matches.append(found)
        elif found.band > matches[position[key]].band:
            matches[position[key]] = found
    return matches, already_owned, unmatched


def new_marks(matches):
    """
    Die Treffer aus match_items(), die eine Markierung tatsächlich ändern:
    Eintrag noch nicht markiert, oder bisher für einen niedrigeren Band
    markiert (dann wird auf den höheren Band angehoben). Treffer, deren
    Band nicht über der vorhandenen Markierung liegt, bleiben außen vor.
    """
    result = []
    for m in matches:
        current = m.entry.get(FLAG_FIELD[m.item.kind]) or ""
        current_band = parse_int(current)
        if not current or (current_band is not None and m.band > current_band):
            result.append(m)
    return result


def build_log(source, mail_count, items, matches, new_matches, already_owned, unmatched,
              problems=(), when=None) -> list:
    """
    Baut die Zeilen des Protokolls "Bestellung einlesen" (eine eigene
    Logdatei je Vorgang, siehe changelog.write_order_log). Enthält nur
    Artikel-/Titelnamen und Bandnummern - keine Adresse, Bestellnummer,
    Preise oder Dateinamen der E-Mails. Artikel ohne passenden Eintrag
    stehen in einem eigenen Abschnitt am Ende.
    """
    when = when or datetime.now()
    kind_label = {KIND_ORDER: "bestellt", KIND_PICKUP: "abholbereit"}
    already_marked = [m for m in matches if m not in new_matches]
    new_ordered = [m for m in new_matches if m.item.kind == KIND_ORDER]
    new_arrived = [m for m in new_matches if m.item.kind == KIND_PICKUP]

    def section(title, rows, empty="(keine)"):
        out = ["", f"--- {title} ({len(rows)}) ---"]
        out += rows if rows else [f"  {empty}"]
        return out

    def match_row(m):
        return f"  {m.entry.get('titel')} | Band {m.band} | Artikel: {m.item.name}"

    lines = [
        "=" * 78,
        f"Bestellung einlesen - {when.strftime('%d.%m.%Y %H:%M:%S')}",
        "=" * 78,
        f"{'Quelle:':<26}{source}",
        f"{'E-Mails:':<26}{mail_count}",
        f"{'Artikel:':<26}{len(items)}",
        f"{'Titel zugeordnet:':<26}{len(matches) + len(already_owned)}",
        f"{'Ohne passenden Eintrag:':<26}{len(unmatched)}",
    ]
    lines += section("Neu als bestellt markiert (hellblau)", [match_row(m) for m in new_ordered])
    lines += section("Neu als angekommen markiert (roter Balken)", [match_row(m) for m in new_arrived])
    lines += section("Bereits markiert (unverändert)", [match_row(m) for m in already_marked])
    lines += section(
        "Bereits im Bestand (nicht markiert)",
        [f"  {m.entry.get('titel')} | Band {m.band} | Bände (bis) = {m.entry.get('baende_bis')}" for m in already_owned],
    )
    if problems:
        lines += section("Nicht lesbare Dateien", [f"  {p}" for p in problems])
    lines += section(
        "ARTIKEL OHNE PASSENDEN EINTRAG",
        [f"  {i.name} | Menge {i.menge} | {kind_label.get(i.kind, i.kind)}" for i in unmatched],
    )
    lines.append("")
    return lines


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
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Optional

_PRICE_RE = re.compile(r"^\d[\d.,]*\s*(EUR|€)$", re.IGNORECASE)
_BAND_RE = re.compile(r"^(?:band\s+|bd\s+|vol\s+|volume\s+)?(\d+)(?=\s|$)")


@dataclass
class OrderItem:
    """Ein bestellter Artikel, wie er in der E-Mail steht."""
    name: str
    menge: int = 1


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
    Speicher vorliegt (z.B. per IMAP abgerufen, siehe mail_fetch.py)."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=("html",))
    if body is None:
        raise ValueError("Die E-Mail enthält keinen HTML-Teil mit einer Artikelliste.")
    return parse_html(body.get_content())


def parse_html(html_text: str) -> list[OrderItem]:
    collector = _RowCollector()
    collector.feed(html_text)
    collector.close()

    items = []
    for cells in collector.rows:
        cells = [c for c in cells if c != ""]
        # Artikelzeile: Name | Anzahl (ganze Zahl) | Preis (z.B. "8,50 EUR")
        if len(cells) >= 3 and cells[1].isdigit() and _PRICE_RE.match(cells[2]):
            items.append(OrderItem(name=cells[0], menge=int(cells[1])))
    if not items:
        raise ValueError("In der E-Mail wurde keine Artikelliste (Name, Anzahl, Preis) gefunden.")
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
      - matches:       Liste von Match
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
    seen_ids = set()
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
            owned = _as_int(entry.get("baende_bis"))
            if owned is not None and str(owned + 1) in rest.split():
                found = Match(item, entry, owned + 1)
                break
        if found is None:
            unmatched.append(item)
            continue

        owned = _as_int(found.entry.get("baende_bis"))
        if owned is not None and found.band <= owned:
            already_owned.append(found)
        elif id(found.entry) not in seen_ids:
            seen_ids.add(id(found.entry))
            matches.append(found)
    return matches, already_owned, unmatched


def _as_int(value) -> Optional[int]:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None

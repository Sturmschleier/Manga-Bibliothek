"""
isbn_lookup.py
----------------
Sucht ISBNs zu fehlenden Bänden und legt Treffer in einer eigenen
Cache-Tabelle `isbn_cache` ab (siehe ensure_isbn_cache_table).

Lookup-Kette (von zuverlässig zu Fallback):
  1. DNB SRU  (Deutsche Nationalbibliothek) — kostenlos, keine Registrierung,
     sehr vollständig für deutsche Verlagsausgaben (Pflichtexemplar-Prinzip:
     jedes in D erschienene Buch muss dort gemeldet werden).
  2. buchhandel.de bzw. manga-passion.de — manueller Fallback-Link, wenn die
     DNB nichts liefert (konfigurierbar, siehe config.py).

Erfordert: requests  (pip install requests --break-system-packages)

Nutzung:
    from isbn_lookup import ensure_isbn_cache_table, fill_missing_isbns
    ensure_isbn_cache_table(db_path)
    report = fill_missing_isbns(db_path, only_month=(9, 2026))
    print(report.summary())
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import requests

import changelog
import config
import shops
import sorting
from logic import parse_int

DNB_SRU_ENDPOINT = "https://services.dnb.de/sru/dnb"
REQUEST_DELAY_SECONDS = 1.5  # freundlich zur DNB-API


# ---------------------------------------------------------------------------
# DB-Hilfsfunktionen
# ---------------------------------------------------------------------------

def ensure_isbn_cache_table(db_path: str) -> None:
    """
    Legt die Tabelle `isbn_cache` an, falls sie noch nicht existiert.

    Eine gefundene ISBN gilt nur für einen bestimmten Band-Stand
    (baende_bis zum Zeitpunkt der Suche) - genau das bildet der
    Primärschlüssel (titel, baende_bis) ab. Ändert sich baende_bis (z.B. durch den "+1"-Button), "verschwindet"
    der Cache-Treffer für diesen Titel automatisch aus der Bestellliste,
    ohne dass er aktiv gelöscht werden müsste. Die ISBN übersteht dadurch
    ein normales "Speichern", ohne dass veraltete ISBNs stillschweigend
    weiterverwendet würden.

    Der Schlüssel ist bewusst `titel` und NICHT die numerische `werke.id`:
    `database.replace_all()` löscht bei jedem Speichern alle Zeilen und
    fügt sie neu ein, wobei JEDER Eintrag eine frische, neu vergebene ID
    bekommt (siehe dort) - die ID ist also gerade NICHT über ein Speichern
    hinweg stabil, der Titel dagegen schon (solange er nicht umbenannt
    wird - eine Umbenennung macht eine alte, an den vorherigen Titel
    gebundene ISBN ohnehin zurecht ungültig).

    `isbn_cache` enthält immer die NORMALE Ausgabe des Bandes. Gefundene
    Sonderausgaben (Collector's Edition, Sammelschuber ...) stehen mit
    demselben Schlüssel getrennt in `isbn_sonderausgaben` - auch dann, wenn
    es (noch) keine normale Ausgabe gibt.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS isbn_cache (
                titel TEXT NOT NULL,
                baende_bis TEXT NOT NULL,
                isbn TEXT NOT NULL,
                gefunden_am TEXT,
                PRIMARY KEY (titel, baende_bis)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS isbn_sonderausgaben (
                titel TEXT NOT NULL,
                baende_bis TEXT NOT NULL,
                isbn TEXT NOT NULL,
                bezeichnung TEXT,
                gefunden_am TEXT,
                PRIMARY KEY (titel, baende_bis, isbn)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


_ENTRY_KEYS = ("id", "titel", "verlag", "typ", "baende_bis", "voe_1")


def _entries_with_cache(conn, entries=None) -> list[dict]:
    """
    Die zu prüfenden Einträge, jeweils ergänzt um "cached_isbn" (normale
    Ausgabe aus isbn_cache, sonst None).

    `entries` sind die Einträge des Zwischenspeichers der Oberfläche - so
    arbeitet der Abgleich mit dem aktuellen Stand, auch wenn noch nicht
    gespeichert wurde. Ohne `entries` (Kommandozeile) wird die Tabelle
    `werke` der Datenbank gelesen.
    """
    if entries is None:
        entries = [dict(zip(_ENTRY_KEYS, row)) for row in conn.execute(f"SELECT {', '.join(_ENTRY_KEYS)} FROM werke")]
    cache = {(t, b): i for t, b, i in conn.execute("SELECT titel, baende_bis, isbn FROM isbn_cache")}
    rows = []
    for e in entries:
        row = {key: e.get(key) for key in _ENTRY_KEYS}
        row["titel"] = row["titel"] or ""
        row["baende_bis"] = row["baende_bis"] or ""
        row["cached_isbn"] = cache.get((row["titel"], row["baende_bis"]))
        rows.append(row)
    return rows


def _naechster_band(baende_bis) -> Optional[int]:
    """Ermittelt den nächsten (noch fehlenden) Band aus 'Bände (bis)' -
    notfalls aus der ersten Zahl im Text (z.B. "12 + Artbook")."""
    owned = parse_int(baende_bis)
    if owned is None:
        m = re.search(r"\d+", str(baende_bis or ""))
        owned = int(m.group()) if m else None
    return owned + 1 if owned is not None else None


def _parse_voe_month(voe1: Optional[str]) -> Optional[tuple[int, int]]:
    """
    Liefert (monat, jahr) aus einer VÖ+1-Zeichenkette oder None - mit
    derselben Datumserkennung wie sorting.py (TT.MM.JJJJ oder MM.JJJJ).
    """
    parsed = sorting.parse_date(voe1)
    if parsed is None:
        return None
    return parsed.month, parsed.year


def _matches_selection(
    voe1: Optional[str], only_month: Optional[tuple[int, int]], only_status: Optional[str]
) -> bool:
    """Prüft, ob ein Titel zur gewählten Auswahl passt: entweder exakter
    VÖ+1-Status (z.B. "TBA"/"NA", nicht case-sensitiv) oder VÖ+1 im
    angegebenen Monat/Jahr. Ist nichts von beidem gesetzt, passt alles."""
    if only_status:
        return (voe1 or "").strip().lower() == only_status.strip().lower()
    if only_month:
        return _parse_voe_month(voe1) == only_month
    return True


# ---------------------------------------------------------------------------
# DNB SRU Lookup (primäre Quelle)
# ---------------------------------------------------------------------------

def _extract_datafields(record, tag: str) -> list:
    """
    Gibt die <datafield tag="..."> Elemente eines MARC21-<record>
    zurück - per echter XML-Bibliothek (xml.etree.ElementTree) statt per
    Regex geparst. Das ist robuster: die DNB kann Namespace-Präfixe,
    Zeilenumbrüche oder abweichende Formatierung verwenden, ohne dass ein
    Regex-Muster daran zerbricht. Die "{*}"-Schreibweise bedeutet "dieses
    Element, unabhängig vom Namespace" - so muss die genaue Namespace-URI
    nicht exakt bekannt sein, egal ob mit oder ohne Präfix.
    """
    return [df for df in record.findall("{*}datafield") if df.get("tag") == tag]


def _subfield(datafield, code: str) -> Optional[str]:
    for sf in datafield.findall("{*}subfield"):
        if sf.get("code") == code:
            return (sf.text or "").strip()
    return None


def _is_valid_isbn(isbn: str) -> bool:
    """Prüft Länge und Prüfziffer einer ISBN ohne Bindestriche: ISBN-13
    (beginnt mit 978/979, Gewichte 1/3, Summe durch 10 teilbar) oder
    ISBN-10 (Gewichte 10..1, Prüfziffer X = 10, Summe durch 11 teilbar)."""
    if len(isbn) == 13 and isbn.isdigit() and isbn[:3] in ("978", "979"):
        return sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(isbn)) % 10 == 0
    if len(isbn) == 10 and isbn[:9].isdigit() and (isbn[9].isdigit() or isbn[9] in "Xx"):
        digits = [int(d) for d in isbn[:9]] + [10 if isbn[9] in "Xx" else int(isbn[9])]
        return sum(d * (10 - i) for i, d in enumerate(digits)) % 11 == 0
    return False


def _clean_isbn(raw: str) -> Optional[str]:
    """Extrahiert die erste gültige ISBN aus Feld 020$a (das oft Zusatztext
    wie '978-3-551-... : EUR 7.50 (Bd. 23)' enthält). Gültig heißt: richtige
    Länge und Prüfziffer (siehe _is_valid_isbn) - eine verstümmelte Nummer
    oder eine andere Zahl im Feld wird so nicht als ISBN übernommen."""
    for candidate in re.findall(r"\d[\d\-]{8,15}[\dXx]", raw or ""):
        isbn = candidate.replace("-", "").upper()
        if _is_valid_isbn(isbn):
            return isbn
    return None


def _year_constraint() -> str:
    """
    CQL-Bedingung, die eine DNB-Anfrage auf das aktuelle Kalenderjahr und
    das Folgejahr einschränkt (automatisch anhand des Systemdatums
    ermittelt, kein fester Jahreswert) - ein gesuchter, noch nicht
    besessener Band ist so gut wie nie älter.
    """
    current_year = datetime.now().year
    return f"(jhr={current_year} or jhr={current_year + 1})"


def _cql_term(value: str) -> str:
    """
    Setzt einen Suchbegriff für eine CQL-Anfrage in Anführungszeichen.

    Zeichen mit Sonderbedeutung werden durch Leerzeichen ersetzt (die DNB
    sucht ohnehin wortweise): Ein " oder \\ im Titel würde die Anfrage
    sonst abbrechen, und * ? ^ wirken auch innerhalb der Anführungszeichen
    als Platzhalter/Anker ("Kaiju No. 8?" liefert z.B. 0 statt 49 Treffer).
    """
    cleaned = re.sub(r'["\\*?^]', " ", value or "")
    return '"' + " ".join(cleaned.split()) + '"'


def _cql_title(titel: str) -> str:
    """
    Titelbedingung für die DNB-Suche: alle Wörter des Titels ODER die
    exakte Wortfolge.

    `tit="..."` allein sucht die exakte Wortfolge - ein Gedankenstrich "–"
    statt "-" oder ein Doppelpunkt ("NieR:Automata") führt dann zu 0
    Treffern ("Nura – Herr der Yokai": 0 statt 27). `tit all "..."` (alle
    Wörter, egal was dazwischen steht) findet diese Titel, verfehlt aber
    solche, die die DNB als ein Wort führt ("Re:Zero": 4 statt 25). Beide
    zusammen finden jeweils das meiste.
    """
    words = re.findall(r"\w+", titel or "")
    if not words:
        return f"tit={_cql_term(titel)}"
    return f'(tit all "{" ".join(words)}" or tit={_cql_term(titel)})'


def _record_title_text(record) -> str:
    """Sammelt den gesamten Titel-/Serientext eines Records (Felder 245,
    490, 830) als einen durchsuchbaren String - genutzt sowohl für den
    Bandnummer- als auch für den Typ-Abgleich. Nicht kleingeschrieben;
    Aufrufer, die Groß-/Kleinschreibung ignorieren wollen (z.B.
    _type_matches), rufen selbst .lower() auf."""
    text_parts = []
    for tag in ("245", "490", "830"):
        for df in _extract_datafields(record, tag):
            for code in ("a", "b", "n", "p", "v"):
                val = _subfield(df, code)
                if val:
                    text_parts.append(val)
    return " ".join(text_parts)


# Unterfelder, in denen die DNB die Bandzählung als eigene Angabe führt:
# 245$n (Zählung des Teils, z.B. "Blue Lock" $n "26"), 490$v/830$v
# (Gesamttitel mit Bandangabe, z.B. "Sanda" $v "14"), 800/810/811$v
# (Gesamttitel über Person/Körperschaft).
_VOLUME_SUBFIELDS = (("245", "n"), ("490", "v"), ("800", "v"), ("810", "v"), ("811", "v"), ("830", "v"))

# Stärke eines Bandnummer-Treffers (siehe _band_match)
BAND_IN_FIELD = 2   # Bandnummer im dafür vorgesehenen Unterfeld - zuverlässig
BAND_IN_TITLE = 1   # nur im Titeltext erkannt - z.B. Sonderausgaben ohne Bandfeld


def _record_volume_numbers(record) -> set[int]:
    """Alle Bandnummern aus den Band-Unterfeldern eines Records (jeweils die
    erste Zahl, führende Nullen spielen keine Rolle: "07" = 7)."""
    numbers = set()
    for tag, code in _VOLUME_SUBFIELDS:
        for df in _extract_datafields(record, tag):
            m = re.search(r"\d+", _subfield(df, code) or "")
            if m:
                numbers.add(int(m.group()))
    return numbers


def _count_number(text: str, number: int) -> int:
    """Wie oft `number` als eigenständige Zahl in `text` vorkommt."""
    return sum(1 for token in re.findall(r"\d+", text or "") if int(token) == number)


def _band_match(record, band: int, titel: Optional[str] = None) -> int:
    """
    Prüft, ob ein Record der gesuchte Band ist, und liefert die Stärke des
    Treffers: BAND_IN_FIELD, BAND_IN_TITLE oder 0 (kein Treffer).

    1. Hat der Record eigene Band-Unterfelder (siehe _VOLUME_SUBFIELDS),
       entscheiden ausschließlich diese. Eine Zahl im Reihentitel ("Kaiju
       No. 8", "7 Seeds") kann so nicht mehr als Bandnummer durchgehen.
    2. Sonst (manche Records führen den Band nur im Titel, z.B. "Konosuba!
       ... Light Novel 10") wird der Titeltext (245 $a/$b/$p) durchsucht.
       Die Zahl muss dort öfter vorkommen als im gesuchten Reihentitel
       `titel` selbst - bei "Kaiju No. 8" zählt eine 8 also erst, wenn sie
       ein zweites Mal auftaucht.
    """
    numbers = _record_volume_numbers(record)
    if numbers:
        return BAND_IN_FIELD if band in numbers else 0

    parts = []
    for df in _extract_datafields(record, "245"):
        for code in ("a", "b", "p"):
            value = _subfield(df, code)
            if value:
                parts.append(value)
    if _count_number(" ".join(parts), band) > _count_number(titel or "", band):
        return BAND_IN_TITLE
    return 0


# Begriffe, an denen Sonderausgaben im DNB-Titel (245) bzw. in der
# Ausgabebezeichnung (250) zu erkennen sind - ermittelt an echten DNB-Daten:
# "Collector's Edition", "Limited Edition", "Variant Edition",
# "Tarot-Edition", "Band 30 mit Sammelschuber", "Band 16-20 im Sammelschuber",
# "mit Acryl-Aufsteller", "Starter Pack", "Bundle", "+ Box",
# "Sonderausgabe" (250), "NARUTO Massiv", "2in1" ... Bewusst NICHT dabei:
# Beigaben der normalen Erstauflage wie "Mit Collector's Print als Extra"
# oder "mit Farbschnitt".
_SPECIAL_EDITION_PATTERNS = [
    re.compile(p) for p in (
        r"\bedition\b", r"schuber", r"sonderausgabe", r"sonderedition", r"\blimit", r"\bvariant",
        r"\bdeluxe\b", r"acryl", r"\bstarter\b", r"\bbundle\b", r"\bpack\b", r"\bbox\b",
        r"\bmassiv\b", r"\d\s*in\s*1\b", r"sammelband", r"omnibus",
    )
]

# Steuerzeichen, mit denen die DNB nicht mitsortierte Artikel einklammert
# ("\x98Die\x9c Braut des Magiers")
_NON_SORT_CHARS = str.maketrans("", "", "\x98\x9c")


def _special_edition(record, titel: Optional[str] = None) -> Optional[str]:
    """
    Erkennt Sonderausgaben (Collector's/Limited/Variant Edition,
    Sammelschuber, Bundles, Sammelbände ...) und liefert ihre Bezeichnung
    für die Anzeige (DNB-Titel, z.B. "Blue Lock – Band 33 – Collector's
    Edition"), bei normalen Ausgaben None.

    Ein Begriff zählt nur, wenn er im Record öfter vorkommt als im gesuchten
    Reihentitel `titel` - "Blue Box 17" ist für die Reihe "Blue Box" also
    eine normale Ausgabe, "Naruto Massiv 5" für die Reihe "Naruto" dagegen
    eine Sonderausgabe.
    """
    main_title = " ".join(
        value for df in _extract_datafields(record, "245")
        for value in (_subfield(df, "a"), _subfield(df, "n"), _subfield(df, "p")) if value
    ).translate(_NON_SORT_CHARS).strip()
    edition = " ".join(
        value for df in _extract_datafields(record, "250") for value in [_subfield(df, "a")] if value
    )
    subtitle = " ".join(
        value for df in _extract_datafields(record, "245") for value in [_subfield(df, "b")] if value
    )
    record_text = f"{main_title} {subtitle} {edition}".casefold()
    titel_text = (titel or "").casefold()
    if not any(len(p.findall(record_text)) > len(p.findall(titel_text)) for p in _SPECIAL_EDITION_PATTERNS):
        return None
    if edition and any(p.search(edition.casefold()) for p in _SPECIAL_EDITION_PATTERNS):
        return f"{main_title} ({edition})"
    return main_title or "Sonderausgabe"


@dataclass
class Sonderausgabe:
    """Eine gefundene Sonderausgabe des gesuchten Bandes."""
    isbn: str
    bezeichnung: str   # DNB-Titel, z.B. "Dandadan – Band 20 mit Sammelschuber"


# Viele Reihen existieren sowohl als Manga/Manhwa-Adaption als auch als
# Light Novel, oft mit eigener, unabhängiger Bandzählung (z.B. Konosuba!) -
# und teils beim selben Verlag, sodass eine Verlagsprüfung allein nicht
# ausreicht (z.B. Tokyopop veröffentlicht Konosuba! als Manga UND als
# Light Novel). Recherche zur tatsächlichen Titelvergabe (z.B. bei
# Tokyopop) zeigt ein konsistentes Muster: Light-Novel-Ausgaben führen
# "Light Novel" explizit im Titel ("... Light Novel, Band 05"), während
# Manga-Ausgaben KEIN Unterscheidungswort wie "Manga" im Titel tragen
# (einfach nur "... Band 14"). Ein einfacher Ausschluss von "Manga" im
# Titel würde daher ins Leere laufen - stattdessen wird für "Light Novel"
# das Vorhandensein des Begriffs VERLANGT (nicht nur seine Abwesenheit bei
# anderen Typen geprüft).
_TYPE_REQUIRE_KEYWORDS = {
    "light novel": {"light novel", "light-novel"},
}
_TYPE_EXCLUDE_KEYWORDS = {
    "manga": {"light novel", "light-novel"},
    "manhwa": {"light novel", "light-novel"},
}


def _type_matches(record, typ: Optional[str]) -> bool:
    """
    Prüft, ob ein DNB-Record zum erwarteten Typ (Manga/Manhwa/Light Novel)
    des Eintrags passt:
      - "Light Novel": der DNB-Titel muss den Begriff "Light Novel"
        explizit enthalten (Light-Novel-Ausgaben führen ihn üblicherweise
        im Titel, Manga-Ausgaben derselben Reihe tun das nicht).
      - "Manga"/"Manhwa": der DNB-Titel darf NICHT den Begriff
        "Light Novel" enthalten (dann handelt es sich erkennbar um die
        Light-Novel-Ausgabe).
      - Unbekannter/fehlender Typ: kein Ausschluss (True), damit fehlende
        Angaben nicht fälschlich Treffer verhindern.
    """
    if not typ:
        return True
    typ_key = typ.strip().lower()
    full_text = _record_title_text(record).lower()

    require = _TYPE_REQUIRE_KEYWORDS.get(typ_key)
    if require:
        return any(keyword in full_text for keyword in require)

    exclude = _TYPE_EXCLUDE_KEYWORDS.get(typ_key)
    if exclude:
        return not any(keyword in full_text for keyword in exclude)

    return True


def _extract_publisher(record) -> Optional[str]:
    """Liest den Verlagsnamen aus Feld 264$b (aktuelles MARC-Feld) oder als
    Fallback aus dem älteren Feld 260$b."""
    for tag in ("264", "260"):
        for df in _extract_datafields(record, tag):
            b = _subfield(df, "b")
            if b:
                return b
    return None


_VERLAG_STOPWORDS = {"verlag", "manga", "comics", "gmbh", "co", "kg", "de"}


def _normalize_verlag(text: str) -> set[str]:
    """Zerlegt einen Verlagsnamen in vergleichbare Kern-Tokens
    (Kleinbuchstaben, ohne Rechtsform-/Gattungs-Füllwörter)."""
    tokens = re.findall(r"[a-zäöüß]+", text.lower())
    return {t for t in tokens if t not in _VERLAG_STOPWORDS and len(t) > 2}


def _verlag_search_term(verlag: Optional[str]) -> Optional[str]:
    """Extrahiert das aussagekräftigste Wort eines Verlagsnamens (z. B.
    'Carlsen' aus 'Carlsen Manga') für die Verwendung direkt in der
    SRU-Anfrage, um die Trefferliste bei der DNB vorab einzuschränken."""
    if not verlag:
        return None
    tokens = re.findall(r"[^\W\d_]+", verlag, re.UNICODE)
    for t in tokens:
        if t.lower() not in _VERLAG_STOPWORDS and len(t) > 2:
            return t
    return tokens[0] if tokens else None


def _publisher_matches(record, verlag: Optional[str]) -> bool:
    """True, wenn sich die Kern-Tokens von `verlag` (z. B. 'Carlsen' aus
    'Carlsen Manga') im DNB-Verlagsfeld wiederfinden. Ohne verlag-Angabe
    oder ohne DNB-Verlagsfeld gilt der Abgleich als nicht widerlegt (True),
    damit fehlende Metadaten nicht fälschlich Treffer ausschließen."""
    if not verlag:
        return True
    dnb_publisher = _extract_publisher(record)
    if not dnb_publisher:
        return True
    wanted = _normalize_verlag(verlag)
    found = _normalize_verlag(dnb_publisher)
    if not wanted:
        return True
    return bool(wanted & found)


def _isbn_from_record(record) -> Optional[str]:
    for df in _extract_datafields(record, "020"):
        a = _subfield(df, "a")
        if a:
            isbn = _clean_isbn(a)
            if isbn:
                return isbn
    return None


def lookup_isbn_dnb(
    titel: str, band: int, verlag: Optional[str] = None, typ: Optional[str] = None,
    log: Optional[list[str]] = None,
) -> tuple[Optional[str], str, list[Sonderausgabe]]:
    """
    Sucht die ISBN eines Bandes bei der DNB in bis zu zwei Durchgängen:

      1. Ist ein Verlag bekannt: SRU-Anfrage direkt mit Titel UND Verlag
         eingeschränkt. Das ist nötig, weil die DNB pro Anfrage maximal
         20 Records liefert - bei umfangreichen oder gleichnamigen Reihen
         kann der gesuchte Band sonst außerhalb dieser ersten 20 Treffer
         liegen und würde nie gefunden.
      2. Liefert das nichts (z. B. weil der Verlagsname bei der DNB
         abweichend erfasst ist): Fallback auf die reine Titelsuche ohne
         Verlagseinschränkung.

    Innerhalb der jeweiligen Treffer wird weiterhin zweistufig zugeordnet:
    zuerst ein Record mit passender Bandnummer UND passendem Verlag, sonst
    ein Record mit nur passender Bandnummer. Records, deren Bandnummer im
    dafür vorgesehenen Unterfeld steht, haben dabei jeweils Vorrang vor
    solchen, bei denen sie nur im Titeltext erkannt wurde (siehe
    _band_match). In beiden Durchgängen wird zusätzlich per
    `typ` geprüft, dass es sich nicht erkennbar um die jeweils andere
    Ausgabe (Manga/Manhwa vs. Light Novel) derselben Reihe handelt - z.B.
    bei Reihen wie Konosuba!, die als Manga UND als Light Novel mit
    jeweils eigener Bandzählung erscheinen.

    Die Anfrage selbst wird zusätzlich auf das aktuelle Kalenderjahr und
    das Folgejahr eingeschränkt (ein gesuchter, noch nicht besessener Band
    ist so gut wie nie älter) - das grenzt die ohnehin auf maximal 20
    Treffer begrenzte DNB-Antwort weiter ein.

    Sonderausgaben (Collector's Edition, Sammelschuber ... - siehe
    _special_edition) werden nie als die ISBN des Bandes gewählt, sondern
    getrennt als Liste zurückgegeben (Verlag muss passen, sofern der
    eingetragene Verlag unter den Treffern vorkommt).

    Gibt (isbn_oder_None, confidence, sonderausgaben) zurück, confidence in
    {"band+verlag", "band_only", "titeltext", "keine"}:
      - "band+verlag": Bandfeld und Verlag passen (sichere Zuordnung)
      - "band_only":   Bandfeld passt, Verlag nicht bestätigt
      - "titeltext":   Bandnummer nur im Titeltext erkannt (z.B.
                       Sonderausgabe ohne Bandfeld) - bitte prüfen

    Ist `log` eine Liste, werden alle abgesetzten SRU-Anfragen (Query +
    volle URL) sowie deren Ergebnisse als Zeilen daran angehängt.
    """
    verlag_term = _verlag_search_term(verlag)
    year_constraint = _year_constraint()

    if verlag_term:
        # "vlg" = Index "Verleger/Firma, Ort" (laut explain-Antwort der DNB);
        # "woe" wäre die Freitextsuche über alle Begriffe.
        query = f"{_cql_title(titel)} and mat=books and {year_constraint} and vlg={_cql_term(verlag_term)}"
        isbn, confidence, specials = _run_dnb_query(query, "mit Verlag", titel, band, verlag, typ, log)
        if isbn:
            return isbn, confidence, specials
        time.sleep(REQUEST_DELAY_SECONDS)
    else:
        specials = []

    query = f"{_cql_title(titel)} and mat=books and {year_constraint}"
    label = "ohne Verlag / Fallback" if verlag_term else "Titel"
    isbn, confidence, more_specials = _run_dnb_query(query, label, titel, band, verlag, typ, log)
    known = {s.isbn for s in specials} | {isbn}
    specials += [s for s in more_specials if s.isbn not in known]
    return isbn, confidence, specials


def _sru_diagnostics(root) -> list[str]:
    """Fehlermeldungen einer SRU-Antwort (<diagnostic>), z.B. bei einer
    ungültigen Anfrage - die DNB liefert dann keine Records, sondern einen
    solchen Hinweis."""
    messages = []
    for diag in root.iter():
        if diag.tag.rsplit("}", 1)[-1] != "diagnostic":
            continue
        texts = [
            (child.text or "").strip() for child in diag
            if child.tag.rsplit("}", 1)[-1] in ("message", "details") and (child.text or "").strip()
        ]
        messages.append(" - ".join(texts) or "unbekannter Fehler")
    return messages


def _run_dnb_query(
    query: str, label: str, titel: str, band: int, verlag: Optional[str], typ: Optional[str],
    log: Optional[list[str]],
) -> tuple[Optional[str], str, list[Sonderausgabe]]:
    """Führt eine einzelne SRU-Anfrage aus, sucht in den Treffern nach der
    Bandnummer (Verlag und Typ als Zuordnungskriterien) und protokolliert
    Anfrage + Ergebnis. Gibt (isbn_oder_None, confidence, sonderausgaben)
    zurück - die ISBN ist immer die einer normalen Ausgabe."""
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": query,
        "recordSchema": "MARC21-xml",
        "maximumRecords": 20,
    }
    request_url = DNB_SRU_ENDPOINT + "?" + urllib.parse.urlencode(params)

    if log is not None:
        log.append(f"  DNB SRU Query ({label}):    {query}")
        log.append(f"  DNB SRU Anfrage ({label}):  {request_url}")

    try:
        resp = requests.get(DNB_SRU_ENDPOINT, params=params, timeout=15)
        resp.raise_for_status()
        xml_text = resp.text
    except requests.RequestException as exc:
        if log is not None:
            log.append(f"  DNB SRU Fehler ({label}):   {exc}")
        return None, "keine", []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        if log is not None:
            log.append(f"  DNB SRU Fehler ({label}):   Antwort ist kein gültiges XML ({exc})")
        return None, "keine", []

    diagnostics = _sru_diagnostics(root)
    if diagnostics:
        if log is not None:
            log.append(f"  DNB SRU Fehler ({label}):   {'; '.join(diagnostics)}")
        return None, "keine", []

    # "{*}" = dieses Element unabhängig vom Namespace/Namespace-Präfix -
    # robust gegenüber Formatierungsdetails der DNB-Antwort, die ein
    # starres Regex-Muster sonst leicht lautlos zum Scheitern bringen
    # könnten (z.B. ein Namespace-Präfix wie "<marc:datafield>"). Die
    # SRU-Hülle heißt ebenfalls <record>; gezählt werden nur die
    # eigentlichen MARC-Records (die mit <datafield>-Einträgen).
    records = [r for r in root.findall(".//{*}record") if r.find("{*}datafield") is not None]
    scored = [(r, _band_match(r, band, titel)) for r in records]
    # Treffer im Bandfeld zuerst (sorted ist stabil: die DNB-Reihenfolge
    # bleibt innerhalb derselben Stärke erhalten)
    band_candidates = [(r, s) for r, s in sorted(scored, key=lambda rs: -rs[1]) if s]
    # Records, die erkennbar zur jeweils ANDEREN Ausgabe (Manga vs. Light
    # Novel) gehören, werden von vornherein ausgeschlossen - unabhängig
    # vom Verlags-Durchgang.
    type_ok_candidates = [(r, s) for r, s in band_candidates if _type_matches(r, typ)]
    excluded_wrong_type = len(band_candidates) - len(type_ok_candidates)

    # Sonderausgaben (Collector's Edition, Sammelschuber ...) von den
    # normalen Ausgaben trennen: gewählt wird nur eine normale Ausgabe.
    normal_candidates = []
    special_candidates = []
    for record, strength in type_ok_candidates:
        bezeichnung = _special_edition(record, titel)
        if bezeichnung is None:
            normal_candidates.append((record, strength))
        else:
            special_candidates.append((record, bezeichnung))

    result_isbn: Optional[str] = None
    result_confidence = "keine"

    # 1. Durchgang: Band + Verlag
    for record, strength in normal_candidates:
        if _publisher_matches(record, verlag):
            isbn = _isbn_from_record(record)
            if isbn:
                result_isbn = isbn
                result_confidence = "band+verlag" if strength == BAND_IN_FIELD else "titeltext"
                break

    # 2. Durchgang: nur Band (schwächere Zuordnung)
    if result_isbn is None:
        for record, strength in normal_candidates:
            isbn = _isbn_from_record(record)
            if isbn:
                result_isbn = isbn
                result_confidence = "band_only" if strength == BAND_IN_FIELD else "titeltext"
                break

    # Sonderausgaben: nur die des eingetragenen Verlags - sofern dieser unter
    # den Treffern überhaupt vorkommt. Sonst ist der Verlag im Eintrag
    # vermutlich veraltet (wie beim 2. Durchgang oben) und alle zählen.
    # Jede ISBN nur einmal.
    publisher_found = any(_publisher_matches(r, verlag) for r, _s in type_ok_candidates)
    specials: list[Sonderausgabe] = []
    for record, bezeichnung in special_candidates:
        if publisher_found and not _publisher_matches(record, verlag):
            continue
        isbn = _isbn_from_record(record)
        if isbn and isbn != result_isbn and all(s.isbn != isbn for s in specials):
            specials.append(Sonderausgabe(isbn, bezeichnung))

    if log is not None:
        in_field = sum(1 for _r, s in band_candidates if s == BAND_IN_FIELD)
        exclude_note = (
            f", davon {excluded_wrong_type} Treffer als andere Ausgabe (Manga/Light Novel) ausgeschlossen"
            if excluded_wrong_type else ""
        )
        log.append(
            f"  DNB SRU Treffer ({label}):  {len(records)} Records gesamt, "
            f"{len(band_candidates)} mit Band {band} "
            f"({in_field} im Bandfeld, {len(band_candidates) - in_field} nur im Titeltext, "
            f"{len(special_candidates)} Sonderausgaben)"
            + exclude_note
        )
        if result_isbn:
            log.append(f"  DNB SRU Ergebnis ({label}): ISBN {result_isbn} (Zuordnung: {result_confidence})")
        else:
            log.append(f"  DNB SRU Ergebnis ({label}): keine normale Ausgabe gefunden")
        for special in specials:
            log.append(f"  DNB SRU Sonderausgabe ({label}): ISBN {special.isbn} – {special.bezeichnung}")

    return result_isbn, result_confidence, specials


def manga_passion_search_url(titel: str) -> str:
    """Alternativer Fallback-Link: manga-passion.de Volltextsuche zur manuellen Prüfung."""
    q = urllib.parse.quote(titel)
    return f"https://www.manga-passion.de/search?q={q}"


def buchhandel_de_search_url(titel: str, year: Optional[int] = None) -> str:
    """
    Standard-Fallback-Link: Suche auf buchhandel.de (Verzeichnis
    Lieferbarer Bücher/VLB) nach gedruckten Büchern (pt=pbook) ab dem
    angegebenen Erscheinungsjahr (Standard: aktuelles Kalenderjahr) bis
    offen, sortiert nach Erscheinungsdatum - damit landet ein noch nicht
    automatisch gefundener, aber bereits angekündigter Band ganz oben in
    der Trefferliste.
    """
    if year is None:
        year = datetime.now().year
    inner_query = f"(ti={titel}) und pt=pbook und ej={year}^*"
    encoded = urllib.parse.quote(inner_query, safe="()*")
    return f"https://buchhandel.de/suche/ergebnisse?query={encoded}&sortField=publicationDate"


def fallback_search_url(titel: str) -> str:
    """
    Liefert den Fallback-Suchlink für einen nicht automatisch gefundenen
    Titel - welcher Anbieter verwendet wird, ist über die zentrale
    Konfiguration (config.json, Schlüssel "isbn_fallback_provider")
    einstellbar: "buchhandel.de" (Standard) oder "manga-passion".
    """
    provider = config.get("isbn_fallback_provider", "buchhandel.de")
    if provider == "manga-passion":
        return manga_passion_search_url(titel)
    return buchhandel_de_search_url(titel)


# ---------------------------------------------------------------------------
# Kombinierte Lookup-Kette
# ---------------------------------------------------------------------------

def lookup_isbn(
    titel: str, band: int, verlag: Optional[str] = None, typ: Optional[str] = None,
    log: Optional[list[str]] = None,
) -> tuple[Optional[str], str, list[Sonderausgabe]]:
    """
    Sucht die ISBN über die DNB (Band+Verlag, dann nur Band als schwächere
    Zuordnung).
    Gibt (isbn_oder_None, quelle, sonderausgaben) zurück; quelle in
    {"dnb (band+verlag)", "dnb (band_only)", "dnb (titeltext)", "keine"}.
    Die ISBN ist immer die der normalen Ausgabe, Sonderausgaben kommen
    getrennt (siehe lookup_isbn_dnb).
    """
    isbn, confidence, sonderausgaben = lookup_isbn_dnb(titel, band, verlag, typ, log=log)
    if isbn:
        return isbn, f"dnb ({confidence})", sonderausgaben

    return None, "keine", sonderausgaben


# ---------------------------------------------------------------------------
# Batch-Verarbeitung
# ---------------------------------------------------------------------------

@dataclass
class LookupResult:
    id: int
    titel: str
    verlag: str
    band: Optional[int]
    isbn: Optional[str]
    quelle: str = "keine"
    fallback_url: Optional[str] = None
    sonderausgaben: list = field(default_factory=list)   # list[Sonderausgabe]


# Markiert in Zusammenfassung und Bestellliste Bände, für die es eine
# normale UND eine Sonderausgabe gibt - das Ergebnisfenster hebt Zeilen mit
# diesem Zeichen golden hervor (siehe gui/isbn_view.py).
SONDERAUSGABE_MARKER = "★"

_UNSICHER_GRUND = {
    "band_only": "Verlag nicht bestätigt",
    "titeltext": "Band nur im Titel erkannt",
}


@dataclass
class LookupReport:
    gefunden: list = field(default_factory=list)
    nicht_gefunden: list = field(default_factory=list)
    log_path: Optional[str] = None
    log_error: Optional[str] = None
    gesamt: int = 0             # so viele Titel waren zur Prüfung ausgewählt
    abgebrochen: bool = False   # vom Nutzer abgebrochen, bevor alle geprüft waren

    def summary(self) -> str:
        total = len(self.gefunden) + len(self.nicht_gefunden)
        lines = [f"{len(self.gefunden)}/{total} ISBNs automatisch gefunden."]
        if self.abgebrochen:
            lines.append(
                f"ABGEBROCHEN: nur {total} von {self.gesamt} Titeln geprüft "
                "(bereits gefundene ISBNs sind gespeichert)."
            )
        lines.append("")
        if self.gefunden:
            sicher = [r for r in self.gefunden if "band+verlag" in r.quelle]
            unsicher = [r for r in self.gefunden if "band+verlag" not in r.quelle]
            lines.append(f"  davon sicher (DNB, Bandfeld + Verlag): {len(sicher)}")
            lines.append(f"  davon unsicher (Verlag nicht bestätigt oder Band nur im Titel): {len(unsicher)}")
            if unsicher:
                lines.append("")
                lines.append("Bitte bei 'unsicher' markierten Titeln die ISBN vor Bestellung kurz prüfen:")
                for r in unsicher:
                    grund = next((g for key, g in _UNSICHER_GRUND.items() if key in r.quelle), "unsicher")
                    lines.append(f"  - {r.titel} Band {r.band} ({r.verlag}) → ISBN {r.isbn} [{grund}]")
            lines.append("")
        mit_sonderausgabe = [r for r in self.gefunden + self.nicht_gefunden if r.sonderausgaben]
        if mit_sonderausgabe:
            lines.append("Sonderausgaben (zusätzlich in der Bestellliste; golden = normale Ausgabe und Sonderausgabe):")
            for r in mit_sonderausgabe:
                prefix = f"  {SONDERAUSGABE_MARKER} " if r.isbn else "  - "
                normal = f"normale Ausgabe ISBN {r.isbn}" if r.isbn else "keine normale Ausgabe gefunden"
                lines.append(f"{prefix}{r.titel} Band {r.band}: {normal}")
                for s in r.sonderausgaben:
                    lines.append(f"{prefix}    Sonderausgabe ISBN {s.isbn} – {s.bezeichnung}")
            lines.append("")
        if self.nicht_gefunden:
            lines.append("Manuell zu prüfen:")
            for r in self.nicht_gefunden:
                lines.append(f"  - {r.titel} Band {r.band} ({r.verlag}) → {r.fallback_url}")
            lines.append("")
        if self.log_path:
            lines.append(f"Log-Datei: {self.log_path}")
        elif self.log_error:
            lines.append(f"Log-Datei konnte nicht geschrieben werden: {self.log_error}")
        return "\n".join(lines)


def fill_missing_isbns(
    db_path: str,
    only_month: Optional[tuple[int, int]] = None,  # (monat, jahr), z.B. (9, 2026)
    only_status: Optional[str] = None,              # z.B. "TBA" oder "NA" (Wert in VÖ +1)
    overwrite: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
    cancel: Optional[threading.Event] = None,
    entries: Optional[list] = None,
) -> LookupReport:
    """
    Durchläuft die Einträge (`entries` = Zwischenspeicher der Oberfläche,
    ohne Angabe die Tabelle `werke`, siehe _entries_with_cache), ermittelt
    für jeden Titel den nächsten Band
    (baende_bis + 1) und versucht die ISBN über die DNB zu finden.
    Ein Treffer landet in `isbn_cache`, verknüpft mit dem Band-Stand
    (baende_bis) zum Zeitpunkt der Suche - siehe ensure_isbn_cache_table().

    Auswahl der zu prüfenden Titel (genau eines von beiden angeben, sonst
    werden alle Titel geprüft):
      - `only_month`: Titel, deren VÖ +1 im angegebenen Monat/Jahr liegt.
      - `only_status`: Titel, deren VÖ +1 exakt diesem Text entspricht
        (z.B. "TBA" oder "NA"), unabhängig vom Datum.

    Jede gefundene ISBN wird sofort in `isbn_cache` gespeichert - bei einem
    Absturz oder Abbruch bleiben die bis dahin gefundenen erhalten.

    `progress(erledigt, gesamt, titel)` wird (falls angegeben) vor jedem
    geprüften Titel aufgerufen. Ist `cancel` gesetzt (threading.Event),
    endet der Abgleich nach dem gerade laufenden Titel; der Bericht hat
    dann `abgebrochen = True`.

    Jede abgesetzte SRU-Anfrage und ihr Ergebnis wird
    mitprotokolliert; am Ende wird das komplette Protokoll als eine Datei
    unter LOG/ (neben der .exe bzw. neben diesem Skript) gespeichert -
    Dateiname mit Datum und Uhrzeit, z.B. isbn_abgleich_2026-08-29_14-32-05.log.
    """
    ensure_isbn_cache_table(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    report = LookupReport()

    if only_status:
        auswahl_label = f'VÖ +1 = "{only_status}"'
    elif only_month:
        auswahl_label = f"{only_month[0]:02d}/{only_month[1]}"
    else:
        auswahl_label = "alle"

    log_lines = [
        "=" * 78,
        f"ISBN-Abgleich - gestartet {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        f"Datenbank:          {db_path}",
        f"Einträge aus:       {'Zwischenspeicher (auch ungespeicherte Änderungen)' if entries is not None else 'Datenbank'}",
        f"Auswahl (VÖ +1):    {auswahl_label}",
        "=" * 78,
        "",
    ]

    try:
        cur = conn.cursor()
        selected = [
            row for row in _entries_with_cache(conn, entries)
            if _matches_selection(row["voe_1"], only_month, only_status)
            and (overwrite or not row["cached_isbn"])
        ]
        report.gesamt = len(selected)

        for index, row in enumerate(selected):
            if cancel is not None and cancel.is_set():
                report.abgebrochen = True
                log_lines.append(f"ABGEBROCHEN durch den Nutzer nach {index} von {len(selected)} Titeln.")
                log_lines.append("")
                break
            if progress is not None:
                progress(index, len(selected), row["titel"])

            band = _naechster_band(row["baende_bis"])
            titel = row["titel"]
            verlag = row["verlag"]
            typ = row["typ"]

            log_lines.append(f"Titel: {titel}")
            log_lines.append(
                f"  Verlag: {verlag or '(unbekannt)'} | Typ: {typ or '(unbekannt)'} | "
                f"gesuchter Band: {band} | VÖ +1: {row['voe_1']}"
            )

            if not band:
                log_lines.append("  Übersprungen: kein gültiger Wert in „Bände (bis)“ vorhanden.")
                log_lines.append("")
                report.nicht_gefunden.append(
                    LookupResult(
                        row["id"], titel, row["verlag"], band, None, "keine",
                        fallback_url=fallback_search_url(titel),
                    )
                )
                continue

            isbn, quelle, sonderausgaben = lookup_isbn(titel, band, verlag, typ, log=log_lines)
            now = datetime.now().isoformat(timespec="seconds")

            if isbn:
                cur.execute(
                    """
                    INSERT INTO isbn_cache (titel, baende_bis, isbn, gefunden_am)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (titel, baende_bis)
                    DO UPDATE SET isbn = excluded.isbn, gefunden_am = excluded.gefunden_am
                    """,
                    (row["titel"], row["baende_bis"], isbn, now),
                )
            # Sonderausgaben dieses Band-Stands durch das aktuelle Suchergebnis ersetzen
            cur.execute(
                "DELETE FROM isbn_sonderausgaben WHERE titel = ? AND baende_bis = ?",
                (row["titel"], row["baende_bis"]),
            )
            cur.executemany(
                "INSERT INTO isbn_sonderausgaben (titel, baende_bis, isbn, bezeichnung, gefunden_am) "
                "VALUES (?, ?, ?, ?, ?)",
                [(row["titel"], row["baende_bis"], s.isbn, s.bezeichnung, now) for s in sonderausgaben],
            )
            conn.commit()  # sofort sichern - ein späterer Absturz/Abbruch verliert den Treffer nicht

            for s in sonderausgaben:
                log_lines.append(f"  SONDERAUSGABE: ISBN {s.isbn} – {s.bezeichnung}")
            if isbn:
                log_lines.append(f"  ERGEBNIS: ISBN {isbn} übernommen (Quelle: {quelle})")
                report.gefunden.append(
                    LookupResult(row["id"], titel, row["verlag"], band, isbn, quelle, sonderausgaben=sonderausgaben)
                )
            else:
                fallback_url = fallback_search_url(titel)
                log_lines.append(f"  ERGEBNIS: keine ISBN der normalen Ausgabe gefunden. Fallback-Link: {fallback_url}")
                report.nicht_gefunden.append(
                    LookupResult(
                        row["id"], titel, row["verlag"], band, None, quelle,
                        fallback_url=fallback_url, sonderausgaben=sonderausgaben,
                    )
                )
            log_lines.append("")

            if index < len(selected) - 1:
                # freundlich zur DNB; ein Abbruch beendet die Wartezeit sofort
                if cancel is not None:
                    cancel.wait(REQUEST_DELAY_SECONDS)
                else:
                    time.sleep(REQUEST_DELAY_SECONDS)

        conn.commit()
    finally:
        conn.close()

    log_lines.append("=" * 78)
    log_lines.append(f"Abgeschlossen {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    log_lines.append(report.summary())
    log_lines.append("=" * 78)

    try:
        report.log_path = changelog.write_isbn_log(log_lines)
    except OSError as exc:
        report.log_error = str(exc)

    return report


# ---------------------------------------------------------------------------
# Fertige Bestellliste mit Links zum gewählten Buchhändler
# ---------------------------------------------------------------------------

def bestellliste_markdown(
    db_path: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    status: Optional[str] = None,
    entries: Optional[list] = None,
) -> str:
    """Erzeugt eine fertige Markdown-Bestellliste mit Links zum gewählten
    Buchhändler (siehe shops.py) - aus `entries` (Zwischenspeicher) bzw.
    ohne Angabe aus der Tabelle `werke`.
    Entweder für Titel, deren VÖ+1 im angegebenen Monat/Jahr liegt
    (month + year), oder für Titel mit einem bestimmten VÖ+1-Status
    (status, z.B. "TBA" oder "NA").

    Je Titel steht zuerst die normale Ausgabe (oder ein Fallback-Suchlink),
    darunter jede bekannte Sonderausgabe als eigene Zeile ("↳ Sonderausgabe:
    ..."). Gibt es für den Band beide, beginnen alle Zeilen dieses Titels
    mit SONDERAUSGABE_MARKER - das Ergebnisfenster hebt sie golden hervor."""
    ensure_isbn_cache_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = _entries_with_cache(conn, entries)
        specials = {}
        for s in conn.execute("SELECT titel, baende_bis, isbn, bezeichnung FROM isbn_sonderausgaben ORDER BY rowid"):
            specials.setdefault((s["titel"], s["baende_bis"]), []).append(s)
    finally:
        conn.close()

    only_month = (month, year) if (month and year) else None

    def cell(value) -> str:
        return str(value if value is not None else "").replace("|", "/")  # "|" würde die Tabelle zerschneiden

    gruppen = []
    for row in rows:
        if not _matches_selection(row["voe_1"], only_month, status):
            continue
        band = _naechster_band(row["baende_bis"])
        row_specials = specials.get((row["titel"], row["baende_bis"]), [])
        marker = f"{SONDERAUSGABE_MARKER} " if row["cached_isbn"] and row_specials else ""
        prefix = f"| {cell(row['voe_1'])} | {marker}"
        suffix = f" | {cell(row['verlag'])} | {cell(band)} |"
        if row["cached_isbn"]:
            zeilen = [f"{prefix}{cell(row['titel'])}{suffix} {row['cached_isbn']} | [öffnen]({shops.order_url(row['cached_isbn'])}) |"]
        else:
            zeilen = [f"{prefix}{cell(row['titel'])}{suffix} — | [öffnen]({fallback_search_url(row['titel'])}) |"]
        for s in row_specials:
            zeilen.append(
                f"{prefix}↳ Sonderausgabe: {cell(s['bezeichnung'])}{suffix} {s['isbn']} | [öffnen]({shops.order_url(s['isbn'])}) |"
            )
        # Chronologisch nach VÖ +1 (echte Datumswerte, nicht als Text - sonst
        # stünde "5.09.2026" hinter "15.09.2026"), bei gleichem Datum nach Titel
        gruppen.append(((sorting.sort_key("voe_1", row["voe_1"]), (row["titel"] or "").lower()), zeilen))
    gruppen.sort(key=lambda g: g[0])

    titel_zeile = f"# Bestellliste {month:02d}/{year}" if only_month else f"# Bestellliste – VÖ +1 = {status}"
    out = [titel_zeile, "", f"Buchhändler: {shops.active_name()}", "", "| Datum | Titel | Verlag | Band | ISBN | Link |", "|---|---|---|---|---|---|"]
    for _key, zeilen in gruppen:
        out.extend(zeilen)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI-Nutzung: python isbn_lookup.py pfad/zur.db 9 2026
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Nutzung: python isbn_lookup.py <db_pfad> [monat jahr | TBA | NA]")
        sys.exit(1)

    db_path = sys.argv[1]
    month_filter = None
    status_filter = None
    if len(sys.argv) == 4:
        month_filter = (int(sys.argv[2]), int(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[2].strip().upper() in ("TBA", "NA"):
        status_filter = sys.argv[2].strip().upper()

    report = fill_missing_isbns(db_path, only_month=month_filter, only_status=status_filter)
    print(report.summary())

    if month_filter:
        print()
        print(bestellliste_markdown(db_path, month_filter[0], month_filter[1]))
    elif status_filter:
        print()
        print(bestellliste_markdown(db_path, status=status_filter))

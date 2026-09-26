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
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

from paths import base_dir
import changelog
import config
import sorting

DNB_SRU_ENDPOINT = "https://services.dnb.de/sru/dnb"
REQUEST_DELAY_SECONDS = 1.5  # freundlich zur DNB-API


# ---------------------------------------------------------------------------
# DB-Hilfsfunktionen
# ---------------------------------------------------------------------------

def ensure_isbn_cache_table(db_path: str) -> None:
    """
    Legt die Tabelle `isbn_cache` an, falls sie noch nicht existiert.

    Ersetzt die frühere Lösung (eine transiente `isbn`-Spalte direkt in
    `werke`, die bei jedem "Speichern" verworfen wurde, weil sie nicht
    Teil des regulären Spaltenmodells war): Eine gefundene ISBN gilt
    ohnehin nur für einen bestimmten Band-Stand (baende_bis zum Zeitpunkt
    der Suche) - genau das bildet der Primärschlüssel (titel, baende_bis)
    ab. Ändert sich baende_bis (z.B. durch den "+1"-Button), "verschwindet"
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
        conn.commit()
    finally:
        conn.close()


def _naechster_band(baende_bis) -> Optional[int]:
    """Ermittelt den nächsten (noch fehlenden) Band aus 'Bände (bis)'."""
    if baende_bis is None:
        return None
    try:
        return int(baende_bis) + 1
    except (TypeError, ValueError):
        m = re.search(r"\d+", str(baende_bis))
        return int(m.group()) + 1 if m else None


def _parse_voe_month(voe1: Optional[str]) -> Optional[tuple[int, int]]:
    """
    Liefert (monat, jahr) aus einer VÖ+1-Zeichenkette oder None.
    Nutzt dieselbe Datumserkennung wie sorting.py (TT.MM.JJJJ ODER
    MM.JJJJ) - vorher wurde hier nur TT.MM.JJJJ verstanden, wodurch ein
    VÖ+1-Wert wie "09.2026" beim Monats-/Jahr-Filter des ISBN-Abgleichs
    übersehen worden wäre, obwohl Tabellensortierung und der Filter
    "Mit Datum" ihn längst korrekt als Datum erkennen.
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
# Log-Datei
# ---------------------------------------------------------------------------

def _write_log_file(lines: list[str]) -> str:
    """Schreibt die gesammelten Log-Zeilen als eine Datei in LOG/ (unterhalb
    des Programmordners bzw. neben der .exe) und gibt den Pfad zurück."""
    log_dir = base_dir() / "LOG"
    log_dir.mkdir(parents=True, exist_ok=True)
    filename = "isbn_abgleich_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    log_path = log_dir / filename
    log_path.write_text("\n".join(lines), encoding="utf-8")
    changelog.prune_isbn_logs()  # nur die neuesten "isbn_log_keep" Logdateien behalten
    return str(log_path)


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


def _clean_isbn(raw: str) -> Optional[str]:
    """Extrahiert die reine ISBN aus Feld 020$a (das oft Zusatztext wie
    '978-3-551-... : EUR 7.50 (Bd. 23)' enthält)."""
    m = re.search(r"(97[89][\d\-]{10,17})", raw)
    if m:
        return re.sub(r"-", "", m.group(1))
    m = re.search(r"([\dXx][\d\-]{8,12}[\dXx])", raw)
    return re.sub(r"-", "", m.group(1)) if m else None


def _year_constraint() -> str:
    """
    CQL-Bedingung, die eine DNB-Anfrage auf das aktuelle Kalenderjahr und
    das Folgejahr einschränkt (automatisch anhand des Systemdatums
    ermittelt, kein fester Jahreswert) - ein gesuchter, noch nicht
    besessener Band ist so gut wie nie älter.
    """
    current_year = datetime.now().year
    return f"(jhr={current_year} or jhr={current_year + 1})"


def _band_variants(band: int) -> list[str]:
    """
    Liefert plausible Schreibweisen einer Bandnummer, da die DNB (und
    Verlage) einstellige Bände uneinheitlich mit oder ohne führende Null
    angeben - z.B. Band 7 als "7" oder als "07".
    """
    variants = [str(band)]
    if 0 <= band < 100:
        padded = f"{band:02d}"
        if padded not in variants:
            variants.append(padded)
    return variants


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


def _title_matches_band(record, band: int) -> bool:
    """Prüft, ob die Bandnummer (mit oder ohne führende Null, z.B. "7" oder
    "07") irgendwo im Titel/Serienfeld des Records vorkommt."""
    full_text = _record_title_text(record)
    alternatives = "|".join(re.escape(v) for v in _band_variants(band))
    return re.search(rf"(?<!\d)(?:{alternatives})(?!\d)", full_text) is not None


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
) -> tuple[Optional[str], str]:
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
    zuerst ein Record mit passender Bandnummer UND passendem Verlag
    (sichere Zuordnung), sonst ein Record mit nur passender Bandnummer
    (schwächere Zuordnung). In beiden Durchgängen wird zusätzlich per
    `typ` geprüft, dass es sich nicht erkennbar um die jeweils andere
    Ausgabe (Manga/Manhwa vs. Light Novel) derselben Reihe handelt - z.B.
    bei Reihen wie Konosuba!, die als Manga UND als Light Novel mit
    jeweils eigener Bandzählung erscheinen.

    Die Anfrage selbst wird zusätzlich auf das aktuelle Kalenderjahr und
    das Folgejahr eingeschränkt (ein gesuchter, noch nicht besessener Band
    ist so gut wie nie älter) - das grenzt die ohnehin auf maximal 20
    Treffer begrenzte DNB-Antwort weiter ein.

    Gibt (isbn_oder_None, confidence) zurück, confidence in
    {"band+verlag", "band_only", "keine"}.

    Ist `log` eine Liste, werden alle abgesetzten SRU-Anfragen (Query +
    volle URL) sowie deren Ergebnisse als Zeilen daran angehängt.
    """
    verlag_term = _verlag_search_term(verlag)
    year_constraint = _year_constraint()

    if verlag_term:
        query = f'tit="{titel}" and mat=books and {year_constraint} and WOE="{verlag_term}"'
        isbn, confidence = _run_dnb_query(query, "mit Verlag", band, verlag, typ, log)
        if isbn:
            return isbn, confidence
        time.sleep(REQUEST_DELAY_SECONDS)

    query = f'tit="{titel}" and mat=books and {year_constraint}'
    label = "ohne Verlag / Fallback" if verlag_term else "Titel"
    return _run_dnb_query(query, label, band, verlag, typ, log)


def _run_dnb_query(
    query: str, label: str, band: int, verlag: Optional[str], typ: Optional[str],
    log: Optional[list[str]],
) -> tuple[Optional[str], str]:
    """Führt eine einzelne SRU-Anfrage aus, sucht in den Treffern nach der
    Bandnummer (Verlag und Typ als Zuordnungskriterien) und protokolliert
    Anfrage + Ergebnis. Gibt (isbn_oder_None, confidence) zurück."""
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
        return None, "keine"

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        if log is not None:
            log.append(f"  DNB SRU Fehler ({label}):   Antwort ist kein gültiges XML ({exc})")
        return None, "keine"

    # "{*}" = dieses Element unabhängig vom Namespace/Namespace-Präfix -
    # robust gegenüber Formatierungsdetails der DNB-Antwort, die ein
    # starres Regex-Muster sonst leicht lautlos zum Scheitern bringen
    # könnten (z.B. ein Namespace-Präfix wie "<marc:datafield>").
    records = root.findall(".//{*}record")
    band_candidates = [r for r in records if _title_matches_band(r, band)]
    # Records, die erkennbar zur jeweils ANDEREN Ausgabe (Manga vs. Light
    # Novel) gehören, werden von vornherein ausgeschlossen - unabhängig
    # vom Verlags-Durchgang.
    type_ok_candidates = [r for r in band_candidates if _type_matches(r, typ)]
    excluded_wrong_type = len(band_candidates) - len(type_ok_candidates)

    result_isbn: Optional[str] = None
    result_confidence = "keine"

    # 1. Durchgang: Band + Verlag
    for record in type_ok_candidates:
        if _publisher_matches(record, verlag):
            isbn = _isbn_from_record(record)
            if isbn:
                result_isbn, result_confidence = isbn, "band+verlag"
                break

    # 2. Durchgang: nur Band (schwächere Zuordnung)
    if result_isbn is None:
        for record in type_ok_candidates:
            isbn = _isbn_from_record(record)
            if isbn:
                result_isbn, result_confidence = isbn, "band_only"
                break

    if log is not None:
        exclude_note = (
            f", davon {excluded_wrong_type} Treffer als andere Ausgabe (Manga/Light Novel) ausgeschlossen"
            if excluded_wrong_type else ""
        )
        log.append(
            f"  DNB SRU Treffer ({label}):  {len(records)} Records gesamt, "
            f"{len(band_candidates)} mit passender Bandnummer "
            f"({'/'.join(_band_variants(band))})"
            + exclude_note
        )
        if result_isbn:
            log.append(f"  DNB SRU Ergebnis ({label}): ISBN {result_isbn} (Zuordnung: {result_confidence})")
        else:
            log.append(f"  DNB SRU Ergebnis ({label}): kein Treffer")

    return result_isbn, result_confidence


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
) -> tuple[Optional[str], str]:
    """
    Sucht die ISBN über die DNB (Band+Verlag, dann nur Band als schwächere
    Zuordnung).
    Gibt (isbn_oder_None, quelle) zurück; quelle in
    {"dnb (band+verlag)", "dnb (band_only)", "keine"}.
    """
    isbn, confidence = lookup_isbn_dnb(titel, band, verlag, typ, log=log)
    if isbn:
        return isbn, f"dnb ({confidence})"

    return None, "keine"


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


@dataclass
class LookupReport:
    gefunden: list = field(default_factory=list)
    nicht_gefunden: list = field(default_factory=list)
    log_path: Optional[str] = None
    log_error: Optional[str] = None

    def summary(self) -> str:
        total = len(self.gefunden) + len(self.nicht_gefunden)
        lines = [f"{len(self.gefunden)}/{total} ISBNs automatisch gefunden.", ""]
        if self.gefunden:
            sicher = sum(1 for r in self.gefunden if "band+verlag" in r.quelle)
            unsicher = sum(1 for r in self.gefunden if "band_only" in r.quelle)
            lines.append(f"  davon sicher (DNB, Band+Verlag): {sicher}")
            lines.append(f"  davon unsicher (DNB, nur Band, Verlag nicht bestätigt): {unsicher}")
            if unsicher:
                lines.append("")
                lines.append("Bitte bei 'unsicher' markierten Titeln die ISBN vor Bestellung kurz prüfen:")
                for r in self.gefunden:
                    if "band_only" in r.quelle:
                        lines.append(f"  - {r.titel} Band {r.band} ({r.verlag}) → ISBN {r.isbn}")
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
) -> LookupReport:
    """
    Durchläuft `werke`, ermittelt für jeden Titel den nächsten Band
    (baende_bis + 1) und versucht die ISBN über die DNB zu finden.
    Ein Treffer landet in `isbn_cache`, verknüpft mit dem Band-Stand
    (baende_bis) zum Zeitpunkt der Suche - siehe ensure_isbn_cache_table().

    Auswahl der zu prüfenden Titel (genau eines von beiden angeben, sonst
    werden alle Titel geprüft):
      - `only_month`: Titel, deren VÖ +1 im angegebenen Monat/Jahr liegt.
      - `only_status`: Titel, deren VÖ +1 exakt diesem Text entspricht
        (z.B. "TBA" oder "NA"), unabhängig vom Datum.

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
        f"Auswahl (VÖ +1):    {auswahl_label}",
        "=" * 78,
        "",
    ]

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT w.id, w.titel, w.verlag, w.typ, w.baende_bis, w.voe_1,
                   c.isbn AS cached_isbn
            FROM werke w
            LEFT JOIN isbn_cache c ON c.titel = w.titel AND c.baende_bis = w.baende_bis
            """
        )
        rows = cur.fetchall()

        for row in rows:
            if not _matches_selection(row["voe_1"], only_month, only_status):
                continue

            if row["cached_isbn"] and not overwrite:
                continue

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

            isbn, quelle = lookup_isbn(titel, band, verlag, typ, log=log_lines)
            time.sleep(REQUEST_DELAY_SECONDS)

            if isbn:
                cur.execute(
                    """
                    INSERT INTO isbn_cache (titel, baende_bis, isbn, gefunden_am)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (titel, baende_bis)
                    DO UPDATE SET isbn = excluded.isbn, gefunden_am = excluded.gefunden_am
                    """,
                    (row["titel"], row["baende_bis"], isbn, datetime.now().isoformat(timespec="seconds")),
                )
                log_lines.append(f"  ERGEBNIS: ISBN {isbn} übernommen (Quelle: {quelle})")
                report.gefunden.append(
                    LookupResult(row["id"], titel, row["verlag"], band, isbn, quelle)
                )
            else:
                fallback_url = fallback_search_url(titel)
                log_lines.append(f"  ERGEBNIS: keine ISBN gefunden. Fallback-Link: {fallback_url}")
                report.nicht_gefunden.append(
                    LookupResult(
                        row["id"], titel, row["verlag"], band, None, quelle,
                        fallback_url=fallback_url,
                    )
                )
            log_lines.append("")

        conn.commit()
    finally:
        conn.close()

    log_lines.append("=" * 78)
    log_lines.append(f"Abgeschlossen {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    log_lines.append(report.summary())
    log_lines.append("=" * 78)

    try:
        report.log_path = _write_log_file(log_lines)
    except OSError as exc:
        report.log_error = str(exc)

    return report


# ---------------------------------------------------------------------------
# Fertige Bestellliste mit Konold-Links generieren
# ---------------------------------------------------------------------------

def konold_url(isbn: str) -> str:
    """
    Verlinkt eine gefundene ISBN zum bevorzugten Online-Buchhändler.
    Welcher das ist, ist über die zentrale Konfiguration (config.json,
    Schlüssel "isbn_shop_url_template") dauerhaft einstellbar - Standard
    ist Konold (konold.buchhandlung.de).
    """
    template = config.get(
        "isbn_shop_url_template",
        "https://konold.buchhandlung.de/shop/action/productDetails?id={isbn}",
    )
    return template.format(isbn=isbn)


def bestellliste_markdown(
    db_path: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    status: Optional[str] = None,
) -> str:
    """Erzeugt eine fertige Markdown-Bestellliste mit Konold-Links.
    Entweder für Titel, deren VÖ+1 im angegebenen Monat/Jahr liegt
    (month + year), oder für Titel mit einem bestimmten VÖ+1-Status
    (status, z.B. "TBA" oder "NA")."""
    ensure_isbn_cache_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT w.titel, w.verlag, w.baende_bis, w.voe_1, c.isbn AS cached_isbn
            FROM werke w
            LEFT JOIN isbn_cache c ON c.titel = w.titel AND c.baende_bis = w.baende_bis
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    only_month = (month, year) if (month and year) else None

    zeilen = []
    for row in rows:
        if not _matches_selection(row["voe_1"], only_month, status):
            continue
        band = _naechster_band(row["baende_bis"])
        if row["cached_isbn"]:
            link = konold_url(row["cached_isbn"])
            zeilen.append((row["voe_1"], row["titel"], row["verlag"], band, row["cached_isbn"], link))
        else:
            zeilen.append((row["voe_1"], row["titel"], row["verlag"], band, "—", fallback_search_url(row["titel"])))

    zeilen.sort(key=lambda z: (z[0] or ""))

    titel_zeile = f"# Bestellliste {month:02d}/{year}" if only_month else f"# Bestellliste – VÖ +1 = {status}"
    out = [titel_zeile, "", "| Datum | Titel | Verlag | Band | ISBN | Link |", "|---|---|---|---|---|---|"]
    for datum, titel, verlag, band, isbn, link in zeilen:
        out.append(f"| {datum} | {titel} | {verlag} | {band} | {isbn} | [öffnen]({link}) |")
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

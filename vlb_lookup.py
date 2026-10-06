"""
vlb_lookup.py
Holt Erscheinungstermine kommender Bände von buchhandel.de (VLB) und
schlägt sie als Werte für "VÖ +1" bis "VÖ +3" vor.

Quelle ist die JSON-Schnittstelle, aus der auch die Suchseite von
buchhandel.de ihre Trefferliste lädt (/jsonapi/products). Sie ist nicht
offiziell dokumentiert und kann sich ändern - alle Feldnamen stehen deshalb
hier an einer Stelle, und bei unerwarteten Antworten wird gemeldet statt
geraten.

Ablauf je Serie:
  1. Suche nach dem Titel (nur Print, ab dem Vorjahr), Pause zwischen den
     Anfragen (Fair Use, siehe REQUEST_DELAY_SECONDS)
  2. Treffer eingrenzen: Verlag passt, Titel endet auf eine Bandnummer,
     keine Sonderausgabe, passender Titelstamm (siehe find_next_volumes)
  3. Die Bände owned+1 ... owned+3 den Spalten VÖ +1 ... VÖ +3 zuordnen

Das Ergebnis sind nur Vorschläge (SeriesResult.changes); geschrieben wird
im Zwischenspeicher (library.apply_vlb_dates), wo die Werte rot markiert
bleiben, bis gespeichert wird.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import requests

import appinfo
from database import VOE_COLUMNS
from isbn_lookup import _SPECIAL_EDITION_PATTERNS, _normalize_verlag
from logic import parse_int

VLB_ENDPOINT = "https://buchhandel.de/jsonapi/products"
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 30

# Fair Use: mindestens so viele Sekunden zwischen zwei Anfragen, dazu ein
# zufälliger Aufschlag. Einmal pro Serie, nur auf Knopfdruck, kein Dauerabruf.
REQUEST_DELAY_SECONDS = 4.0
REQUEST_DELAY_JITTER_SECONDS = 2.0

# Nach so vielen Fehlern in Folge wird der Abruf abgebrochen (Seite nicht
# erreichbar, gesperrt oder geändert) statt weiter anzufragen.
MAX_CONSECUTIVE_ERRORS = 3

# Gesucht wird ab dem Vorjahr: ein noch fehlender Band ist selten älter, und
# bei langen Reihen kommen so die neuesten Bände zuerst und vollständig.
SEARCH_LOOKBACK_YEARS = 1

# VÖ-Werte, bei denen nie nachgefragt wird. "NA" und "TBA" bleiben bewusst
# dabei: "NA" heißt nur, dass beim letzten "+1" kein Folgetermin da war.
SKIP_VOE1_STATUS = ("fortlaufend", "gestoppt", "beendet")
# Platzhalter, die ein gefundener Termin immer ersetzen darf
PLACEHOLDER_STATUS = ("", "na", "tba")

SLOTS = len(VOE_COLUMNS)

# Auswahl, welche Serien abgefragt werden (nach VÖ +1), um die Abfrage zu verkürzen
SCOPE_ALL = "alle"
SCOPE_DATE = "datum"    # in VÖ +1 steht ein Datum
SCOPE_TBA = "tba"
SCOPE_NA = "na"
SCOPES = (SCOPE_ALL, SCOPE_DATE, SCOPE_TBA, SCOPE_NA)


class VlbError(Exception):
    """Abruf nicht möglich oder Antwort nicht auswertbar."""


# ---------------------------------------------------------------------------
# Datumsformate
# ---------------------------------------------------------------------------

_DATE_DMY_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
_DATE_MY_RE = re.compile(r"^\s*(\d{1,2})\.(\d{4})\s*$")
_DATE_Y_RE = re.compile(r"^\s*(\d{4})\s*$")


@dataclass(frozen=True)
class VlbDate:
    """Ein Erscheinungsdatum in der Genauigkeit, in der das VLB es liefert:
    Tag, nur Monat oder nur Jahr. Ein ungenaues Datum bleibt ungenau - es
    wird nicht zum 1. des Monats aufgefüllt."""

    year: int
    month: Optional[int] = None
    day: Optional[int] = None

    @property
    def precision(self) -> int:
        return 3 if self.day else 2 if self.month else 1

    def text(self) -> str:
        if self.day:
            return f"{self.day:02d}.{self.month:02d}.{self.year}"
        if self.month:
            return f"{self.month:02d}.{self.year}"
        return str(self.year)


def parse_vlb_date(value) -> Optional[VlbDate]:
    """TT.MM.JJJJ, MM.JJJJ oder JJJJ -> VlbDate; alles andere (Freitext,
    leer, unmögliches Datum wie 31.02.2026) -> None."""
    text = str(value or "")
    m = _DATE_DMY_RE.match(text)
    if m:
        day, month, year = (int(g) for g in m.groups())
        try:
            datetime(year, month, day)
        except ValueError:
            return None
        return VlbDate(year, month, day)
    m = _DATE_MY_RE.match(text)
    if m:
        month, year = (int(g) for g in m.groups())
        return VlbDate(year, month) if 1 <= month <= 12 else None
    m = _DATE_Y_RE.match(text)
    if m and 1900 <= int(m.group(1)) <= 2100:
        return VlbDate(int(m.group(1)))
    return None


# ---------------------------------------------------------------------------
# Auswahl der Einträge
# ---------------------------------------------------------------------------

def skip_reason(entry: dict) -> Optional[str]:
    """Grund, warum für diesen Eintrag nicht abgefragt wird, sonst None.

    Übersprungen werden: "Komplett" = Ja (alles vorhanden), VÖ +1 mit
    "Fortlaufend" (kein fester Termin, z.B. digitale Reihen, oder man ist
    nicht auf Stand), "Gestoppt" oder "Beendet". Die Spalte "Beendet" zählt
    nicht - sie sagt nur, dass die Reihe abgeschlossen ist, nicht dass man
    sie komplett hat. "NA" und "TBA" werden abgefragt."""
    if not (entry.get("titel") or "").strip():
        return "kein Titel"
    if (entry.get("komplett") or "").strip().lower() == "ja":
        return "Komplett"
    status = (entry.get("voe_1") or "").strip().lower()
    if status in SKIP_VOE1_STATUS:
        return f"VÖ +1: {entry['voe_1'].strip()}"
    if owned_volumes(entry) is None:
        return "Bände (bis) nicht lesbar"
    return None


def in_scope(entry: dict, scope: str = SCOPE_ALL) -> bool:
    """Passt der Eintrag zur Auswahl? "datum" = VÖ +1 enthält ein gültiges
    Datum (TT.MM.JJJJ, MM.JJJJ oder JJJJ), "tba"/"na" = VÖ +1 ist genau das
    (ohne Rücksicht auf Groß-/Kleinschreibung), "alle" = jeder Eintrag."""
    voe1 = (entry.get("voe_1") or "").strip()
    if scope == SCOPE_DATE:
        return parse_vlb_date(voe1) is not None
    if scope in (SCOPE_TBA, SCOPE_NA):
        return voe1.lower() == scope
    return True


def count_by_scope(entries: list[dict]) -> dict[str, int]:
    """Wie viele Serien jede Auswahl abfragen würde (nach der Überspringregel)."""
    todo = [e for e in entries if skip_reason(e) is None]
    return {scope: sum(1 for e in todo if in_scope(e, scope)) for scope in SCOPES}


def owned_volumes(entry: dict) -> Optional[int]:
    """Anzahl vorhandener Bände aus "Bände (bis)" - notfalls die erste Zahl
    im Text (z.B. "12 + Artbook"); leer zählt als 0."""
    raw = entry.get("baende_bis")
    if not str(raw or "").strip():
        return 0
    value = parse_int(raw)
    if value is None:
        m = re.search(r"\d+", str(raw))
        value = int(m.group()) if m else None
    return value


# ---------------------------------------------------------------------------
# Titel vergleichen
# ---------------------------------------------------------------------------

_LIGHT_NOVEL_RE = re.compile(r"[\s(\[–-]*light[\s-]*novels?\)?\]?", re.IGNORECASE)
_LN_SUFFIX_RE = re.compile(r"[\s–-]*\b(?:novel|ln)$", re.IGNORECASE)
_TITLE_SPLIT_RE = re.compile(r"\s[–-]\s|:")
_BAND_WORDS = {"band", "bd", "vol", "volume", "teil", "nr"}
_SPECIAL_EXTRA = [re.compile(p) for p in (r"doppelband", r"jubil", r"collector", r"artbook", r"fanbook")]
_QUERY_UNSAFE_RE = re.compile(r'[()"\\^*?]')


def normalize(text: str) -> str:
    """Kleingeschrieben, Apostroph entfernt, Satzzeichen zu Leerzeichen:
    "Angels of Death: Episode. 0 06" -> "angels of death episode 0 06"."""
    text = (text or "").casefold().replace("’", "").replace("'", "")
    return " ".join(re.sub(r"[^\w]+", " ", text).replace("_", " ").split())


def _strip_light_novel(titel: str) -> str:
    """Titel ohne Light-Novel-Zusatz: "… – Light Novel", "… (Light Novel)" und
    am Ende "… Novel" oder "… LN" (so nennen Verlage ihre Ausgaben)."""
    text = _LIGHT_NOVEL_RE.sub(" ", titel or "").strip(" –-:,.")
    return _LN_SUFFIX_RE.sub("", text).strip(" –-:,.")


def _plain_ln(normalized: str) -> str:
    """Wie _strip_light_novel, aber für bereits normalisierte Titel."""
    text = re.sub(r"\blight novels?\b", " ", normalized)
    return " ".join(re.sub(r"\b(?:novels?|ln)$", " ", text).split())


def search_query(entry: dict, today: Optional[datetime] = None) -> str:
    """Suchanfrage im Syntax der buchhandel.de-Suche. Bei Light Novels ohne
    den Zusatz "Light Novel" - das VLB führt ihn oft nicht im Titel."""
    titel = (entry.get("titel") or "").strip()
    if (entry.get("typ") or "").strip().lower() == "light novel":
        titel = _strip_light_novel(titel) or titel
    titel = " ".join(_QUERY_UNSAFE_RE.sub(" ", titel).split())
    year = (today or datetime.now()).year - SEARCH_LOOKBACK_YEARS
    return f"(ti={titel}) und pt=pbook und ej={year}^*"


def fallback_query(entry: dict, today: Optional[datetime] = None) -> Optional[str]:
    """Kürzere Suche für Titel mit Untertitel ("A Wild Last Boss Appeared! –
    Der …"), die als Ganzes 0 Treffer liefern: nur der Teil vor " – " bzw.
    ":". None, wenn sich dadurch nichts ändert."""
    short = dict(entry, titel=_TITLE_SPLIT_RE.split(entry.get("titel") or "")[0].strip())
    query = search_query(short, today)
    return query if query != search_query(entry, today) and short["titel"] else None


def _split_volume(title: str, ln: bool = False) -> Optional[tuple[str, int]]:
    """Zerlegt einen VLB-Titel in (Titelstamm, Bandnummer), wenn er auf eine
    Bandnummer endet - "Angels of Death: Episode. 0 06" -> ("angels of death
    episode 0", 6). Titel ohne Nummer am Ende (z.B. "… 12 + Box") -> None.
    Bei Light Novels (`ln`) zählt auch "Doppelband 02" als Bandnummer."""
    tokens = normalize(title).split()
    if ln:   # "… Doppelband 02 (Light Novel)": der Zusatz steht hinter der Nummer
        while tokens and tokens[-1] in ("light", "novel", "novels", "ln"):
            tokens.pop()
    if not tokens or not tokens[-1].isdigit():
        return None
    band = int(tokens[-1])
    stem = tokens[:-1]
    band_words = _BAND_WORDS | {"doppelband"} if ln else _BAND_WORDS
    while stem and stem[-1] in band_words:
        stem.pop()
    if not stem:
        return None
    return " ".join(stem), band


def _is_special(stem: str, series: str) -> bool:
    """Sonderausgabe, wenn ein Begriff wie "Edition" oder "Box" im Stamm
    öfter vorkommt als im eigenen Reihentitel."""
    patterns = [*_SPECIAL_EDITION_PATTERNS, *_SPECIAL_EXTRA]
    return any(len(p.findall(stem)) > len(p.findall(series)) for p in patterns)


def _publisher_ok(product: dict, verlag: str) -> bool:
    wanted = _normalize_verlag(verlag or "")
    found = _normalize_verlag(product.get("publisher") or "")
    return not wanted or not found or bool(wanted & found)


@dataclass
class Volume:
    band: int
    date: VlbDate
    isbn: str
    title: str


def _product_text(product: dict) -> str:
    return " ".join(x for x in (product.get("title"), product.get("subTitle")) if x)


def _has_light_novel(product: dict) -> bool:
    return bool(re.search(r"light[\s-]*novel", _product_text(product), re.IGNORECASE))


def _looks_like_light_novel(product: dict) -> bool:
    """Light Novels erkennt man am Titel: "Light Novel", "… - Novel 25", "… LN"."""
    return bool(re.search(r"light[\s-]*novel|\bnovel\b|\bLN\b", _product_text(product), re.IGNORECASE))


def _covers(series: str, stem: str) -> bool:
    """Gehört der Titelstamm zur Serie? Der erste Titelbegriff muss gleich
    sein, alle weiteren Begriffe der Serie müssen in dieser Reihenfolge
    vorkommen - so passt "Assassin's Creed: Die Geschichte von Iga" auch auf
    "Assassin's Creed Shadows: Die Geschichte von Iga (Manga)"."""
    wanted, found = series.split(), stem.split()
    if not wanted or not found or wanted[0] != found[0]:
        return False
    position = 0
    for word in wanted:
        try:
            position = found.index(word, position) + 1
        except ValueError:
            return False
    return True


def find_next_volumes(entry: dict, products: list[dict]) -> tuple[dict[int, Volume], str]:
    """
    Wählt aus den VLB-Treffern die Bände der Serie dieses Eintrags aus.

    Gibt ({Bandnummer: Volume}, Hinweis) zurück; der Hinweis ist leer oder
    erklärt, warum nichts (Eindeutiges) gefunden wurde.

    Ein Treffer gehört zur Serie, wenn der Verlag passt, der Titel auf eine
    Bandnummer endet, mit dem Serientitel des Eintrags beginnt und keine
    Sonderausgabe ist. Kurze Titel treffen oft mehrere Serien mit gleichem
    Anfang ("Arifureta" und "Arifureta … Zero"); dann gewinnt der Titelstamm,
    der genau dem Eintrag entspricht, sonst der, in dem der besessene Band
    vorkommt. Bleibt es mehrdeutig, wird nichts vorgeschlagen.
    """
    titel = entry.get("titel") or ""
    is_ln = (entry.get("typ") or "").strip().lower() == "light novel"
    series = _plain_ln(normalize(titel)) if is_ln else normalize(titel)
    # Das VLB lässt einen Untertitel oft weg: "A Wild Last Boss Appeared! 05"
    # für "A Wild Last Boss Appeared! – Der schwarzgeflügelte Overlord"
    short = normalize(_TITLE_SPLIT_RE.split(titel)[0])
    exact_names = {series, _plain_ln(short) if is_ln else short} - {""}
    owned = owned_volumes(entry) or 0

    typ = (entry.get("typ") or "").strip().lower()
    products = [
        p for p in products
        if (p.get("productType") or "pbook") == "pbook" and _publisher_ok(p, entry.get("verlag"))
    ]
    if is_ln:
        # Nur Treffer, die erkennbar Light Novels sind - sonst würde die
        # Manga-Ausgabe derselben Reihe untergemischt
        products = [p for p in products if _looks_like_light_novel(p)]
    elif typ in ("manga", "manhwa"):
        products = [p for p in products if not _has_light_novel(p)]

    groups: dict[str, dict[int, Volume]] = {}
    for product in products:
        split = _split_volume(product.get("title") or "", is_ln)
        if split is None:
            continue
        stem, band = split
        stem_plain = _plain_ln(stem) if is_ln else stem
        if stem_plain not in exact_names and not _covers(series, stem_plain):
            continue
        if _is_special(stem_plain, series):
            continue
        date = parse_vlb_date(product.get("publicationDate"))
        if date is None:
            continue
        volume = Volume(band, date, str(product.get("identifier") or ""), product.get("title") or "")
        known = groups.setdefault(stem_plain, {}).get(band)
        # Mehrere Ausgaben desselben Bandes: die mit dem früheren Datum nehmen
        if known is None or _date_key(volume.date) < _date_key(known.date):
            groups[stem_plain][band] = volume

    if not groups:
        return {}, "keine passenden Treffer"
    exact = [stem for stem in groups if stem in exact_names]
    if len(exact) == 1:
        return groups[exact[0]], ""
    holding = [stem for stem, volumes in groups.items() if owned in volumes] if owned else []
    if len(holding) == 1:
        return groups[holding[0]], ""
    if len(groups) == 1 and not owned:
        return next(iter(groups.values())), ""
    return {}, "mehrdeutig (Treffer: " + "; ".join(sorted(groups)[:3]) + ")"


def _date_key(date: VlbDate) -> tuple[int, int, int]:
    return date.year, date.month or 0, date.day or 0


# ---------------------------------------------------------------------------
# Vorschläge für VÖ +1 ... VÖ +3
# ---------------------------------------------------------------------------

def should_write(current: str, new: VlbDate) -> bool:
    """Darf `new` den bisherigen Wert eines VÖ-Feldes ersetzen?
      - leer, "NA", "TBA": ja
      - anderes Datum: ja, sofern das neue nicht ungenauer ist (ein
        vorhandenes Tagesdatum wird nicht durch "04.2026" ersetzt)
      - gleiches Datum oder Freitext (z.B. "Band 17 11.06.2025"): nein"""
    text = (current or "").strip()
    if text.lower() in PLACEHOLDER_STATUS:
        return True
    existing = parse_vlb_date(text)
    if existing is None or existing == new:
        return False
    return new.precision >= existing.precision


@dataclass
class SeriesResult:
    """Ergebnis für einen Eintrag. `changes` = {"voe_1": "13.01.2027", ...}
    (nur Felder, die sich ändern würden)."""

    entry_id: object
    titel: str
    status: str                    # neu | aktuell | keine_neuen | uebersprungen | unklar | fehler
    note: str = ""
    changes: dict = field(default_factory=dict)
    previous: dict = field(default_factory=dict)  # bisherige Werte dieser Felder (Schutz vor Zwischenänderungen)
    volumes: list = field(default_factory=list)   # gefundene neue Bände (Volume)


def plan_entry(entry: dict, products: list[dict]) -> SeriesResult:
    """Wertet die Treffer für einen Eintrag aus (ohne Netzwerk)."""
    result = SeriesResult(entry.get("id"), entry.get("titel") or "", "keine_neuen")
    volumes, note = find_next_volumes(entry, products)
    if not volumes:
        result.status, result.note = "unklar", note or "keine passenden Treffer"
        return result

    owned = owned_volumes(entry) or 0
    for slot, column in enumerate(VOE_COLUMNS, start=1):
        volume = volumes.get(owned + slot)
        if volume is None:
            break   # Lücke: spätere Bände dürfen nicht in frühere Spalten rutschen
        result.volumes.append(volume)
        if should_write(entry.get(column) or "", volume.date):
            result.changes[column] = volume.date.text()
            result.previous[column] = entry.get(column) or ""
    if not result.volumes:
        later = sorted(b for b in volumes if b > owned)
        result.note = f"nächster Band {owned + 1} noch nicht angekündigt" + (
            f" (bekannt: Band {later[0]})" if later else "")
    elif not result.changes:
        result.status = "aktuell"
    else:
        result.status = "neu"
    return result


# ---------------------------------------------------------------------------
# Abruf
# ---------------------------------------------------------------------------

def fetch_products(query: str, session: Optional[requests.Session] = None) -> list[dict]:
    """Eine Anfrage an buchhandel.de; gibt die Produktliste (neueste zuerst) zurück."""
    http = session or requests
    try:
        response = http.get(
            VLB_ENDPOINT,
            params={
                "filter[products][query]": query,
                "page[number]": 1,
                "page[size]": PAGE_SIZE,
                "sort[publicationDate]": "desc",
            },
            headers={
                "User-Agent": f"MangaLibrary/{appinfo.VERSION} (private Bibliotheksverwaltung)",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise VlbError(f"keine Verbindung zu buchhandel.de ({exc.__class__.__name__})") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise VlbError(f"buchhandel.de antwortet mit Status {response.status_code}")
    if response.status_code != 200:
        raise VlbError(f"unerwarteter Status {response.status_code}")
    try:
        data = response.json()["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise VlbError("Antwort von buchhandel.de nicht auswertbar (Schnittstelle geändert?)") from exc
    if not isinstance(data, list):
        raise VlbError("Antwort von buchhandel.de nicht auswertbar (Schnittstelle geändert?)")
    return data


def check_entries(
    entries: list[dict],
    progress: Optional[Callable[[int, int, str], None]] = None,
    cancel: Optional[threading.Event] = None,
    scope: str = SCOPE_ALL,
    fetch: Callable[[str], list[dict]] = fetch_products,
    sleep: Callable[[float], None] = time.sleep,
    delay: float = REQUEST_DELAY_SECONDS,
    jitter: float = REQUEST_DELAY_JITTER_SECONDS,
) -> tuple[list[SeriesResult], bool]:
    """
    Fragt alle nicht übersprungenen Einträge nacheinander ab (mit Pause
    zwischen den Anfragen) und gibt (Ergebnisse, abgebrochen) zurück. `scope`
    (SCOPES) beschränkt die Abfrage nach VÖ +1; Einträge außerhalb der
    Auswahl tauchen im Ergebnis nicht auf.
    `progress(erledigt, gesamt, titel)` meldet den Fortschritt, `cancel`
    bricht nach dem laufenden Titel ab. Bei MAX_CONSECUTIVE_ERRORS Fehlern
    in Folge wird der Rest nicht mehr abgefragt.
    """
    results: list[SeriesResult] = []
    todo = []
    for entry in entries:
        if not in_scope(entry, scope):
            continue
        reason = skip_reason(entry)
        if reason:
            results.append(SeriesResult(entry.get("id"), entry.get("titel") or "", "uebersprungen", reason))
        else:
            todo.append(entry)

    errors = 0
    cancelled = False
    for index, entry in enumerate(todo):
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        if progress:
            progress(index, len(todo), entry.get("titel") or "")
        try:
            products = fetch(search_query(entry))
            alternative = None if products else fallback_query(entry)
            if alternative:
                sleep(delay + random.uniform(0, jitter))
                products = fetch(alternative)
        except VlbError as exc:
            errors += 1
            results.append(SeriesResult(entry.get("id"), entry.get("titel") or "", "fehler", str(exc)))
            if errors >= MAX_CONSECUTIVE_ERRORS:
                cancelled = True
                break
        else:
            errors = 0
            results.append(plan_entry(entry, products))
        if index < len(todo) - 1:
            sleep(delay + random.uniform(0, jitter))
    return results, cancelled

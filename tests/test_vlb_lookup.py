"""
tests/test_vlb_lookup.py
Tests für vlb_lookup.py - ohne Netzwerkzugriff. Die Produktlisten sind den
echten Antworten von buchhandel.de nachempfunden (Stand Oktober 2026).
"""

import threading

import pytest

import vlb_lookup as vlb
from vlb_lookup import VlbDate


def product(title, date, publisher="TOKYOPOP GmbH", isbn="978", sub=None, ptype="pbook"):
    return {
        "title": title, "subTitle": sub, "publicationDate": date, "publisher": publisher,
        "identifier": isbn, "productType": ptype,
    }


ANGELS_EPISODE = [
    product("Angels of Death: Episode. 0 06", "13.01.2027", isbn="5908"),
    product("Angels of Death: Episode. 0 05", "14.10.2026", isbn="5892"),
    product("Angels of Death: Episode. 0 04", "08.07.2026", isbn="5885"),
    product("Angels of Death: Episode. 0 03", "10.04.2026", isbn="5878"),
]
ANGELS_MAIN = [
    product("Angels of Death 12 + Box", "09.07.2025"),
    product("Angels of Death 12", "09.07.2025"),
    product("Angels of Death 11", "09.04.2025"),
    product("Jubiläumsedition: Angels of Death 01", "09.10.2024"),
    product("Red Devils - Angels of Death", "29.07.2025", publisher="booXperts - logiXperts GmbH"),
    product("Death in the City of Angels", "15.05.2026", publisher="epubli", sub="Part 1: In the Pictures"),
]


def entry(titel, baende=0, **kw):
    values = {"id": 1, "titel": titel, "baende_bis": str(baende), "verlag": "Tokyopop", "typ": "Manga",
              "komplett": "Nein", "beendet": "Nein", "voe_1": "", "voe_2": "", "voe_3": ""}
    values.update(kw)
    return values


# ------------------------------------------------------------------ Datum

@pytest.mark.parametrize("text, expected", [
    ("13.01.2027", VlbDate(2027, 1, 13)),
    ("3.1.2027", VlbDate(2027, 1, 3)),
    ("04.2026", VlbDate(2026, 4)),
    ("2027", VlbDate(2027)),
    (" 04.2026 ", VlbDate(2026, 4)),
])
def test_parse_vlb_date_formats(text, expected):
    assert vlb.parse_vlb_date(text) == expected


@pytest.mark.parametrize("text", [
    None, "", "TBA", "Fortlaufend", "31.02.2026", "13.2026", "00.2026", "Band 17 11.06.2025", "12",
])
def test_parse_vlb_date_rejects_everything_else(text):
    assert vlb.parse_vlb_date(text) is None


def test_date_text_keeps_precision():
    assert VlbDate(2026, 4).text() == "04.2026"
    assert VlbDate(2026, 4, 3).text() == "03.04.2026"
    assert VlbDate(2027).text() == "2027"


# --------------------------------------------------------- Überspringregel

@pytest.mark.parametrize("kw, skipped", [
    ({}, False),
    ({"komplett": "Ja"}, True),
    ({"komplett": "ja"}, True),
    ({"beendet": "Ja"}, False),             # Spalte "Beendet" zählt nicht
    ({"voe_1": "Fortlaufend"}, True),
    ({"voe_1": " fortlaufend "}, True),
    ({"voe_1": "Gestoppt"}, True),
    ({"voe_1": "Beendet"}, True),
    ({"voe_1": "NA"}, False),               # NA wird abgefragt
    ({"voe_1": "TBA"}, False),              # TBA wird abgefragt
    ({"voe_1": "14.10.2026"}, False),
    ({"titel": " "}, True),
    ({"baende_bis": "viele"}, True),
])
def test_skip_reason(kw, skipped):
    values = {**entry("Serie", 4), **kw}
    assert (vlb.skip_reason(values) is not None) is skipped


def test_owned_volumes_variants():
    assert vlb.owned_volumes({"baende_bis": "12"}) == 12
    assert vlb.owned_volumes({"baende_bis": "12 + Artbook"}) == 12
    assert vlb.owned_volumes({"baende_bis": ""}) == 0
    assert vlb.owned_volumes({}) == 0
    assert vlb.owned_volumes({"baende_bis": "viele"}) is None


# ---------------------------------------------------------------- Suche

def test_search_query_uses_title_print_and_lookback_year():
    from datetime import datetime
    q = vlb.search_query(entry("Blue Lock (Neuedition)"), today=datetime(2026, 10, 6))
    assert q == "(ti=Blue Lock Neuedition) und pt=pbook und ej=2025^*"


def test_search_query_drops_light_novel_suffix():
    from datetime import datetime
    e = entry("Accel World – Light Novel", 5, typ="Light Novel")
    assert vlb.search_query(e, today=datetime(2026, 1, 1)) == "(ti=Accel World) und pt=pbook und ej=2025^*"


# ------------------------------------------------------------- Zuordnung

def test_new_volumes_fill_slots_in_order():
    result = vlb.plan_entry(entry("Angels of Death Episode.0", 4, voe_1="14.10.2026"), ANGELS_EPISODE)
    assert [v.band for v in result.volumes] == [5, 6]
    assert result.changes == {"voe_2": "13.01.2027"}   # voe_1 stimmt schon
    assert result.status == "neu"


def test_up_to_three_slots_and_only_beyond_owned():
    products = [product(f"Serie {n}", f"{n:02d}.01.2027") for n in range(1, 9)]
    result = vlb.plan_entry(entry("Serie", 2), products)
    assert [v.band for v in result.volumes] == [3, 4, 5]
    assert result.changes == {"voe_1": "03.01.2027", "voe_2": "04.01.2027", "voe_3": "05.01.2027"}


def test_na_and_tba_are_replaced():
    for status in ("NA", "TBA", ""):
        result = vlb.plan_entry(entry("Angels of Death Episode.0", 5, voe_1=status), ANGELS_EPISODE)
        assert result.changes == {"voe_1": "13.01.2027"}


def test_gap_stops_assignment():
    products = [product("Serie 4", "01.04.2027"), product("Serie 5", "01.05.2027")]
    result = vlb.plan_entry(entry("Serie", 2), products)
    assert result.volumes == [] and result.changes == {}
    assert "Band 3" in result.note and "Band 4" in result.note
    products = [product("Serie 3", "01.03.2027"), product("Serie 5", "01.05.2027")]
    result = vlb.plan_entry(entry("Serie", 2), products)
    assert [v.band for v in result.volumes] == [3]       # Band 5 darf nicht in VÖ +2 rutschen
    assert result.changes == {"voe_1": "01.03.2027"}


def test_nothing_new_is_reported_as_current():
    current = entry("Angels of Death Episode.0", 4, voe_1="14.10.2026", voe_2="13.01.2027")
    result = vlb.plan_entry(current, ANGELS_EPISODE)
    assert result.status == "aktuell" and result.changes == {}


def test_owned_all_volumes_means_no_new():
    result = vlb.plan_entry(entry("Angels of Death Episode.0", 6), ANGELS_EPISODE)
    assert result.status == "keine_neuen" and result.changes == {}


def test_main_series_ignores_special_editions_and_other_titles():
    products = ANGELS_MAIN + ANGELS_EPISODE + [product("Angels of Death 13", "13.01.2027")]
    volumes, note = vlb.find_next_volumes(entry("Angels of Death", 12), products)
    assert sorted(volumes) == [11, 12, 13]       # "12 + Box", Jubiläum, Red Devils usw. fehlen
    assert note == ""
    result = vlb.plan_entry(entry("Angels of Death", 12), products)
    assert result.changes == {"voe_1": "13.01.2027"}


def test_spinoff_series_is_not_mixed_into_main_series():
    volumes, _ = vlb.find_next_volumes(entry("Angels of Death", 12), ANGELS_EPISODE)
    # "angels of death episode 0 06" beginnt zwar mit dem Titel, hat aber einen anderen Stamm und
    # nicht den besessenen Band 12 -> nicht eindeutig
    assert volumes == {}


def test_short_title_picks_stem_holding_owned_volume():
    products = [
        product("Arifureta - Der Kampf zurück in meine Welt 16", "18.05.2026", publisher="Altraverse GmbH"),
        product("Arifureta - Der Kampf zurück in meine Welt 15", "13.10.2025", publisher="Altraverse GmbH"),
        product("Arifureta - Der Kampf zurück in meine Welt - Zero 04", "14.09.2026", publisher="Altraverse GmbH"),
        product("Arifureta - Der Kampf zurück in meine Welt - Zero 03", "15.06.2026", publisher="Altraverse GmbH"),
    ]
    volumes, note = vlb.find_next_volumes(entry("Arifureta", 16, verlag="Altraverse"), products)
    assert sorted(volumes) == [15, 16] and note == ""
    # Kommt der besessene Band in beiden Reihen vor, wird nicht geraten
    products.append(product("Arifureta - Der Kampf zurück in meine Welt 3", "01.01.2025", publisher="Altraverse GmbH"))
    volumes, note = vlb.find_next_volumes(entry("Arifureta", 3, verlag="Altraverse"), products)
    assert volumes == {} and note.startswith("mehrdeutig")


def test_publisher_must_match():
    products = [product("Serie 3", "01.03.2027", publisher="Carlsen Verlag GmbH")]
    volumes, note = vlb.find_next_volumes(entry("Serie", 2, verlag="Tokyopop"), products)
    assert volumes == {} and note
    volumes, _ = vlb.find_next_volumes(entry("Serie", 2, verlag="Carlsen Manga"), products)
    assert sorted(volumes) == [3]
    volumes, _ = vlb.find_next_volumes(entry("Serie", 2, verlag=""), products)
    assert sorted(volumes) == [3]


def test_light_novel_prefers_titles_with_light_novel():
    products = [
        product("Accel World, Band 06", "01.02.2027"),                       # Manga-Ausgabe
        product("Accel World Light Novel, Band 05", "01.12.2026"),
        product("Accel World Light Novel, Band 06", "01.03.2027"),
    ]
    e = entry("Accel World – Light Novel", 5, typ="Light Novel")
    volumes, _ = vlb.find_next_volumes(e, products)
    assert volumes[6].date == VlbDate(2027, 3, 1)


def test_manga_ignores_light_novel_titles():
    products = [product("Konosuba 20", "01.02.2027"), product("Konosuba Light Novel 20", "01.03.2027")]
    volumes, _ = vlb.find_next_volumes(entry("Konosuba", 19), products)
    assert volumes[20].date == VlbDate(2027, 2, 1)


def test_partial_dates_are_kept_partial_and_unparseable_dates_ignored():
    products = [product("Serie 3", "04.2026"), product("Serie 4", "2027"), product("Serie 5", "demnächst")]
    result = vlb.plan_entry(entry("Serie", 2), products)
    assert result.changes == {"voe_1": "04.2026", "voe_2": "2027"}


def test_duplicate_editions_take_earliest_date():
    products = [product("Serie 3", "10.05.2027", isbn="b"), product("Serie 3", "01.05.2027", isbn="a")]
    volumes, _ = vlb.find_next_volumes(entry("Serie", 2), products)
    assert volumes[3].isbn == "a"


def test_ebooks_are_ignored():
    products = [product("Serie 3", "01.03.2027", ptype="ebook")]
    assert vlb.find_next_volumes(entry("Serie", 2), products)[0] == {}


def test_light_novel_naming_variants_of_publishers():
    # Tokyopop: "… - Novel 25"; Dokico: "… Doppelband 02 (Light Novel)"; Altraverse: "LN" im Titel der Datenbank
    novel = vlb.plan_entry(
        entry("Accel World – Light Novel", 25, typ="Light Novel"),
        [product("Accel World - Novel 26", "01.03.2027"), product("Accel World 9", "01.01.2027")],
    )
    assert [v.band for v in novel.volumes] == [26]
    double = vlb.plan_entry(
        entry("Arifureta – Der Kampf zurück in meine Welt", 1, typ="Light Novel", verlag="Dokico"),
        [product("Arifureta – Der Kampf zurück in meine Welt, Doppelband 02 (Light Novel)", "29.12.2026",
                 publisher="Dokico")],
    )
    assert double.changes == {"voe_1": "29.12.2026"}
    ln = vlb.plan_entry(
        entry("Blade & Bastard LN", 4, typ="Light Novel"),
        [product("Blade & Bastard Light Novel 5", "01.05.2027"), product("Blade & Bastard 5", "01.02.2027")],
    )
    assert ln.changes == {"voe_1": "01.05.2027"}


def test_light_novel_entry_never_takes_manga_volumes():
    manga = [product("Blade & Bastard 5", "01.02.2027")]
    result = vlb.plan_entry(entry("Blade & Bastard LN", 4, typ="Light Novel"), manga)
    assert result.changes == {} and result.status == "unklar"


def test_title_may_be_shorter_than_vlb_title():
    products = [product("Assassin's Creed Shadows: Die Geschichte von Iga (Manga) 02", "21.01.2027"),
                product("Assassin's Creed Shadows: Die Geschichte von Iga (Manga) 01", "21.07.2026")]
    result = vlb.plan_entry(entry("Assassin's Creed: Die Geschichte von Iga", 1), products)
    assert result.changes == {"voe_1": "21.01.2027"}
    assert vlb.find_next_volumes(entry("Iga Assassin", 1), products)[0] == {}


def test_fallback_query_only_for_titles_with_subtitle():
    e = entry("A Wild Last Boss Appeared! – Der schwarzgeflügelte Overlord", 5)
    assert vlb.fallback_query(e).startswith("(ti=A Wild Last Boss Appeared!)")
    assert vlb.fallback_query(entry("Blue Lock", 5)) is None
    assert vlb.fallback_query(entry("Re:Zero", 5)) is not None


def test_no_hits():
    result = vlb.plan_entry(entry("Unbekannt", 2), [])
    assert result.status == "unklar" and result.changes == {}


# ------------------------------------------------ vorhandene Werte schützen

@pytest.mark.parametrize("current, new, expected", [
    ("", VlbDate(2027, 1, 13), True),
    ("NA", VlbDate(2027, 1, 13), True),
    ("tba", VlbDate(2027, 1, 13), True),
    ("14.10.2026", VlbDate(2026, 10, 14), False),            # gleich
    ("14.10.2026", VlbDate(2026, 10, 21), True),             # Verschiebung
    ("14.10.2026", VlbDate(2026, 10), False),                # nicht ungenauer machen
    ("10.2026", VlbDate(2026, 10, 14), True),                # genauer machen
    ("Band 17 11.06.2025", VlbDate(2027, 1, 13), False),     # Freitext bleibt
    ("JP16", VlbDate(2027, 1, 13), False),
])
def test_should_write(current, new, expected):
    assert vlb.should_write(current, new) is expected


# ------------------------------------------------------------ Abruf & Pausen

def test_check_entries_skips_pauses_and_collects():
    entries = [
        entry("Angels of Death Episode.0", 4, id=1),
        entry("Fertig", 3, id=2, komplett="Ja"),
        entry("Laufend", 3, id=3, voe_1="Fortlaufend"),
        entry("Angels of Death", 12, id=4),
    ]
    queries, sleeps, seen = [], [], []

    def fetch(query):
        queries.append(query)
        return ANGELS_EPISODE + ANGELS_MAIN

    results, cancelled = vlb.check_entries(
        entries, progress=lambda d, t, titel: seen.append((d, t, titel)), fetch=fetch, sleep=sleeps.append,
        delay=4, jitter=0,
    )
    assert not cancelled
    assert len(queries) == 2                          # übersprungene Serien werden nicht abgefragt
    assert sleeps == [4]                              # nur zwischen den Anfragen, nicht danach
    assert seen == [(0, 2, "Angels of Death Episode.0"), (1, 2, "Angels of Death")]
    by_id = {r.entry_id: r for r in results}
    assert by_id[2].status == by_id[3].status == "uebersprungen"
    assert by_id[1].changes == {"voe_1": "14.10.2026", "voe_2": "13.01.2027"}


def test_check_entries_retries_with_short_title_when_nothing_found():
    queries, sleeps = [], []

    def fetch(query):
        queries.append(query)
        return [] if "Der Untertitel" in query else [product("Lange Serie 3", "01.03.2027")]

    e = entry("Lange Serie – Der Untertitel", 2)
    results, _ = vlb.check_entries([e], fetch=fetch, sleep=sleeps.append, delay=4, jitter=0)
    assert len(queries) == 2 and "Der Untertitel" not in queries[1]
    assert sleeps == [4]   # auch vor der zweiten Anfrage wird gewartet
    assert results[0].changes == {"voe_1": "01.03.2027"}


def test_check_entries_cancel_stops_before_next_request():
    cancel = threading.Event()
    calls = []

    def fetch(query):
        calls.append(query)
        cancel.set()
        return []

    results, cancelled = vlb.check_entries(
        [entry("A", 1, id=1), entry("B", 1, id=2)], cancel=cancel, fetch=fetch, sleep=lambda s: None
    )
    assert cancelled and len(calls) == 1 and len(results) == 1


def test_check_entries_aborts_after_repeated_errors():
    def fetch(query):
        raise vlb.VlbError("Status 429")

    entries = [entry(f"S{i}", 1, id=i) for i in range(10)]
    results, cancelled = vlb.check_entries(entries, fetch=fetch, sleep=lambda s: None)
    assert cancelled
    assert len(results) == vlb.MAX_CONSECUTIVE_ERRORS
    assert all(r.status == "fehler" for r in results)


def test_check_entries_single_error_does_not_abort():
    answers = [vlb.VlbError("kurz weg"), ANGELS_EPISODE, ANGELS_EPISODE]

    def fetch(query):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    entries = [entry(f"S{i}", 1, id=i) for i in range(3)]
    results, cancelled = vlb.check_entries(entries, fetch=fetch, sleep=lambda s: None)
    assert not cancelled and results[0].status == "fehler" and len(results) == 3


class FakeResponse:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code, self._payload, self._bad = status, payload, bad_json

    def json(self):
        if self._bad:
            raise ValueError("kein JSON")
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_fetch_products_sends_expected_request():
    session = FakeSession(FakeResponse(payload={"data": [{"title": "x"}], "meta": {}}))
    assert vlb.fetch_products("(ti=Serie) und pt=pbook", session) == [{"title": "x"}]
    url, kwargs = session.calls[0]
    assert url == vlb.VLB_ENDPOINT
    assert kwargs["params"]["filter[products][query]"] == "(ti=Serie) und pt=pbook"
    assert kwargs["params"]["sort[publicationDate]"] == "desc"
    assert "MangaLibrary" in kwargs["headers"]["User-Agent"]


@pytest.mark.parametrize("response", [
    FakeResponse(status=429), FakeResponse(status=503), FakeResponse(status=403),
    FakeResponse(bad_json=True), FakeResponse(payload={"nope": 1}), FakeResponse(payload={"data": "x"}),
])
def test_fetch_products_reports_problems_instead_of_guessing(response):
    with pytest.raises(vlb.VlbError):
        vlb.fetch_products("q", FakeSession(response))


# ------------------------------------------------------------------ Auswahl

@pytest.mark.parametrize("voe_1, scope, expected", [
    ("14.10.2026", vlb.SCOPE_DATE, True),
    ("10.2026", vlb.SCOPE_DATE, True),
    ("TBA", vlb.SCOPE_DATE, False),
    ("Band 17 11.06.2025", vlb.SCOPE_DATE, False),
    ("", vlb.SCOPE_DATE, False),
    ("TBA", vlb.SCOPE_TBA, True),
    (" tba ", vlb.SCOPE_TBA, True),
    ("NA", vlb.SCOPE_TBA, False),
    ("NA", vlb.SCOPE_NA, True),
    ("na", vlb.SCOPE_NA, True),
    ("14.10.2026", vlb.SCOPE_NA, False),
    ("", vlb.SCOPE_ALL, True),
    ("TBA", vlb.SCOPE_ALL, True),
])
def test_in_scope(voe_1, scope, expected):
    assert vlb.in_scope(entry("Serie", 3, voe_1=voe_1), scope) is expected


def test_count_by_scope_uses_skip_rules():
    entries = [
        entry("A", 1, voe_1="14.10.2026"), entry("B", 1, voe_1="TBA"), entry("C", 1, voe_1="NA"),
        entry("D", 1, voe_1="TBA", komplett="Ja"), entry("E", 1, voe_1="Fortlaufend"), entry("F", 1, voe_1=""),
    ]
    assert vlb.count_by_scope(entries) == {"alle": 4, "datum": 1, "tba": 1, "na": 1}


def test_check_entries_only_queries_selected_scope():
    queries = []
    entries = [entry("Mit Datum", 1, id=1, voe_1="14.10.2026"), entry("Ohne", 1, id=2, voe_1="TBA"),
               entry("Fertig", 1, id=3, voe_1="TBA", komplett="Ja")]
    results, _ = vlb.check_entries(
        entries, scope=vlb.SCOPE_TBA, fetch=lambda q: queries.append(q) or [], sleep=lambda s: None
    )
    assert len(queries) == 1 and "Ohne" in queries[0]
    assert {r.entry_id: r.status for r in results} == {2: "unklar", 3: "uebersprungen"}   # "Mit Datum" fehlt ganz

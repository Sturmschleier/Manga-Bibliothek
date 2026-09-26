"""
shops.py
Online-Buchhändler, zu denen die ISBNs der Bestellliste verlinkt werden.

Der Standard-Buchhändler kommt weiterhin aus der Konfiguration
(config.json: "isbn_shop_name" / "isbn_shop_url_template", Standard Konold).
Zusätzlich gibt es alternative Anbieter zur Auswahl (Dropdown im Dialog
"ISBN-Abgleich / Bestellliste"); die gewählte Alternative wird dauerhaft in
config.json ("isbn_shop_active") gemerkt.

Bewusst ohne Netzwerk-/Qt-Abhängigkeiten, damit sowohl der Dialog als auch
isbn_lookup.py dieses Modul nutzen können.
"""

import config

# Alternative Anbieter: Anzeigename -> Link-Vorlage ({isbn} wird ersetzt).
ALTERNATIVE_SHOPS = {
    "Thalia": "https://www.thalia.de/suche?sq={isbn}",
    "Amazon": "https://www.amazon.de/s?k={isbn}",
}


def available() -> dict:
    """Alle wählbaren Anbieter (Name -> Vorlage); der konfigurierte
    Standard-Buchhändler steht an erster Stelle."""
    primary_name = str(config.get("isbn_shop_name", "Konold") or "Konold")
    primary_template = str(config.get("isbn_shop_url_template") or "")
    shops = {primary_name: primary_template}
    for name, template in ALTERNATIVE_SHOPS.items():
        shops.setdefault(name, template)
    return shops


def active_name() -> str:
    """Name des aktuell gewählten Anbieters; ist der gespeicherte Name
    unbekannt (z.B. nach einer Konfigurationsänderung), gilt der
    Standard-Buchhändler."""
    shops = available()
    chosen = config.get("isbn_shop_active", "")
    return chosen if chosen in shops else next(iter(shops))


def set_active(name: str) -> None:
    if name in available():
        config.set_value("isbn_shop_active", name)


def order_url(isbn: str, shop: str = None) -> str:
    """Link zur ISBN beim gewählten (oder angegebenen) Anbieter."""
    shops = available()
    template = shops.get(shop or active_name()) or next(iter(shops.values()))
    return template.format(isbn=isbn)

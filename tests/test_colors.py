"""Tests für die Verlagsfarben in colors.py."""

import colors


def test_alle_verlage_bekommen_verschiedene_farben():
    verlage = [f"Verlag {i}" for i in range(len(colors.VERLAG_PALETTE))]
    colors.set_verlag_universe(verlage)
    farben = [colors.verlag_color(v) for v in verlage]
    assert len(set(farben)) == len(verlage)


def test_farbe_ist_stabil_und_ignoriert_gross_kleinschreibung():
    colors.set_verlag_universe(["Altraverse", "Carlsen Manga"])
    assert colors.verlag_color("Altraverse") == colors.verlag_color(" altraverse ")


def test_leerer_verlag_hat_keine_farbe():
    assert colors.verlag_color("") is None
    assert colors.verlag_color("   ") is None


def test_mehr_verlage_als_palette_fuehrt_nicht_zum_fehler():
    verlage = [f"V{i}" for i in range(len(colors.VERLAG_PALETTE) + 5)]
    colors.set_verlag_universe(verlage)
    assert all(colors.verlag_color(v) in colors.VERLAG_PALETTE for v in verlage)

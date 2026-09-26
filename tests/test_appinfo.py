"""
tests/test_appinfo.py
Tests für appinfo.py: Versionsnummer und die Liste der verwendeten Module
im Dialog "Hilfe → Über …".
"""

import re

import appinfo


def test_version_is_semantic():
    assert re.fullmatch(r"\d+\.\d+\.\d+", appinfo.VERSION)


def test_components_list_runtime_and_all_libraries():
    components = appinfo.components(qt_version="6.11.2")
    names = [c.name for c in components]
    assert names[:3] == ["Python", "Qt", "SQLite"]
    assert names[3:] == [name for name, *_ in appinfo.LIBRARIES]
    assert all(c.zweck and c.lizenz for c in components)


def test_installed_libraries_report_their_version():
    # in der Test-Umgebung sind die Abhängigkeiten aus requirements.txt installiert
    versions = {c.name: c.version for c in appinfo.components()}
    assert re.match(r"\d+\.\d+", versions["requests"])
    assert re.match(r"\d+\.\d+", versions["keyring"])
    assert "Qt" not in versions   # ohne Qt-Version kein Qt-Eintrag


def test_missing_package_is_reported_as_not_installed(monkeypatch):
    monkeypatch.setattr(appinfo, "LIBRARIES", (("Gibt es nicht", ("gibt-es-nicht-xyz",), "Test", "MIT"),))
    missing = appinfo.components()[-1]
    assert (missing.name, missing.version) == ("Gibt es nicht", None)
    assert "Gibt es nicht: nicht installiert" in appinfo.about_text()


def test_about_text_contains_version_link_and_data_dir():
    text = appinfo.about_text(qt_version="6.11.2", data_dir="E:/Manga/Work")
    assert text.startswith(f"Manga & Light Novel Bibliothek {appinfo.VERSION}")
    assert appinfo.REPOSITORY_URL in text
    assert "Datenordner: E:/Manga/Work" in text
    assert "Qt: 6.11.2" in text

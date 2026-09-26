"""
tests/test_config.py
Tests für config.py: sicheres Schreiben, Umgang mit einer beschädigten
config.json, typsicheres Lesen und die Prüfung im Konfigurations-Editor.
"""

import json

import pytest

import config


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path


def test_save_writes_complete_file_without_leftovers(cfg_file):
    config.set_value("isbn_log_keep", 7)
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["isbn_log_keep"] == 7
    assert not (cfg_file.parent / "config.json.tmp").exists()


def test_broken_file_gives_defaults_and_is_kept_as_defekt(cfg_file):
    cfg_file.write_text('{"mail_imap_host": "imap.gmx.net", kaputt', encoding="utf-8")
    assert config.problem() and "JSON" in config.problem()
    assert config.load()["isbn_shop_name"] == config.DEFAULTS["isbn_shop_name"]

    config.set_value("follow_selection_after_edit", False)

    kept = cfg_file.parent / "config.json.defekt"
    assert kept.read_text(encoding="utf-8").startswith('{"mail_imap_host": "imap.gmx.net"')  # nichts verloren
    assert config.problem() is None and config.get_bool("follow_selection_after_edit") is False


def test_missing_file_is_no_problem(cfg_file):
    assert config.problem() is None
    config.ensure_file_exists()
    assert json.loads(cfg_file.read_text(encoding="utf-8")) == config.DEFAULTS


def test_defaults_are_not_changed_by_callers(cfg_file):
    config.load()["colors_enabled"]["voe1"] = False
    assert config.DEFAULTS["colors_enabled"]["voe1"] is True


@pytest.mark.parametrize("stored, expected", [
    (True, True), (False, False), ("false", False), ("Nein", False), ("ja", True), ("1", True), ("quatsch", True),
])
def test_get_bool_understands_text_values(cfg_file, stored, expected):
    config.set_value("follow_selection_after_edit", stored)   # Standard ist True
    assert config.get_bool("follow_selection_after_edit") is expected


def test_validate_accepts_defaults_and_unknown_keys():
    cfg = dict(config.DEFAULTS, eigener_schluessel="egal")
    assert config.validate(cfg) == []


def test_validate_reports_wrong_types_and_values():
    cfg = dict(config.DEFAULTS)
    cfg.update({
        "follow_selection_after_edit": "false",     # Text statt true/false
        "isbn_log_keep": "zehn",
        "mail_imap_port": True,                      # bool ist keine Portnummer
        "sidebar_width_fraction": 1,                 # ganze Zahl ist als Zahl in Ordnung
        "isbn_fallback_provider": "google",
        "isbn_shop_url_template": "https://shop.example/suche",
        "colors_enabled": {"voe1": "ja"},
    })
    problems = "\n".join(config.validate(cfg))
    assert "follow_selection_after_edit" in problems and "true oder false" in problems
    assert "isbn_log_keep" in problems and "mail_imap_port" in problems
    assert "sidebar_width_fraction" not in problems
    assert "isbn_fallback_provider" in problems
    assert "{isbn}" in problems
    assert "colors_enabled“ → „voe1" in problems

"""
tests/test_library.py
Tests für den Speicher-Puffer (library.LibraryBuffer): Änderungen,
Rückgängig/Wiederholen, "ungespeicherte Änderungen" und Markierungen.
"""

import pytest

import logic
import order_mail
from library import MAX_UNDO_STEPS, LibraryBuffer


def _buffer():
    return LibraryBuffer([
        {"id": 1, "titel": "Sanda", "baende_bis": "12", "gelesen_bis": "12", "voe_1": "01.10.2026", "voe_2": "",
         "voe_3": "", "bestellt": "", "angekommen": ""},
        {"id": 2, "titel": "Blue Lock", "baende_bis": "30", "gelesen_bis": "28", "voe_1": "TBA", "voe_2": "",
         "voe_3": "", "bestellt": "", "angekommen": ""},
    ])


def test_fresh_buffer_is_clean_and_has_no_history():
    b = _buffer()
    assert not b.dirty and not b.can_undo and not b.can_redo


def test_add_gets_negative_temp_ids_and_is_undoable():
    b = _buffer()
    first = b.add({"titel": "Neu A"})
    second = b.add({"titel": "Neu B"})
    assert (first["id"], second["id"]) == (-1, -2)
    assert b.dirty and len(b.undo_stack) == 2
    assert b.undo() and [e["titel"] for e in b.data] == ["Sanda", "Blue Lock", "Neu A"]


def test_undo_back_to_saved_state_is_not_dirty_and_redo_restores():
    b = _buffer()
    b.update(1, {"kommentar": "neu"})
    assert b.dirty
    assert b.undo() and not b.dirty
    assert b.redo() and b.find(1)["kommentar"] == "neu" and b.dirty


def test_rejected_action_creates_no_undo_step_and_keeps_redo():
    b = _buffer()
    b.update(1, {"kommentar": "x"})
    b.undo()
    assert b.can_redo
    # "+1" auf "Gelesen bis" über "Bände (bis)" hinaus wird abgelehnt
    assert b.increment_gelesen(1) == logic.EXCEEDS
    assert not b.can_undo and b.can_redo        # nichts passiert -> Wiederholen bleibt möglich


def test_invalid_number_leaves_everything_unchanged():
    b = _buffer()
    b.find(2)["baende_bis"] = "viele"
    b.load(b.data)                               # als gespeicherten Stand übernehmen
    assert b.increment_baende(2) is None
    assert not b.dirty and not b.can_undo


def test_update_without_real_change_creates_no_undo_step():
    b = _buffer()
    b.update(1, {"titel": "Sanda"})
    assert not b.can_undo and not b.dirty


def test_new_action_after_undo_discards_redo():
    b = _buffer()
    b.update(1, {"kommentar": "a"})
    b.undo()
    b.update(2, {"kommentar": "b"})
    assert not b.can_redo


def test_delete_and_undo():
    b = _buffer()
    removed = b.delete(1)
    assert removed["titel"] == "Sanda" and b.find(1) is None
    b.undo()
    assert b.find(1)["titel"] == "Sanda"


def test_increment_baende_shifts_dates_and_clears_only_reached_marks():
    b = _buffer()
    b.find(1).update({"bestellt": "14", "angekommen": "13"})
    assert b.increment_baende(1) == 13
    entry = b.find(1)
    assert entry["voe_1"] == "NA"                                  # kein weiterer Termin
    assert (entry["bestellt"], entry["angekommen"]) == ("14", "")


def test_update_raising_bande_clears_reached_marks():
    b = _buffer()
    b.find(1)["bestellt"] = "13"
    b.update(1, {"baende_bis": "13"})
    assert b.find(1)["bestellt"] == ""


def test_import_skips_existing_titles_case_insensitive():
    b = _buffer()
    imported, skipped = b.import_entries([{"titel": "sanda"}, {"titel": "Neu"}, {"titel": "NEU"}])
    assert (imported, skipped) == (1, 2)
    assert b.find(-1)["titel"] == "Neu" and len(b.undo_stack) == 1


def test_import_of_only_known_titles_is_no_change():
    b = _buffer()
    assert b.import_entries([{"titel": "Blue Lock"}]) == (0, 1)
    assert not b.can_undo


def test_apply_order_matches_sets_band_numbers_as_one_undo_step():
    b = _buffer()
    matches, _, _ = order_mail.match_items(
        [
            order_mail.OrderItem("Sanda - Band 14"),
            order_mail.OrderItem("Blue Lock - Band 31", kind=order_mail.KIND_PICKUP),
        ],
        b.data,
    )
    new = b.apply_order_matches(matches)
    assert len(new) == 2
    assert (b.find(1)["bestellt"], b.find(2)["angekommen"]) == ("14", "31")
    assert len(b.undo_stack) == 1
    assert b.apply_order_matches(matches) == [] and len(b.undo_stack) == 1   # zweites Einlesen ändert nichts


def test_clear_marks():
    b = _buffer()
    b.find(1).update({"bestellt": "14", "angekommen": "14"})
    b.load(b.data)
    b.clear_marks(1)
    assert (b.find(1)["bestellt"], b.find(1)["angekommen"]) == ("", "") and b.can_undo


def test_exception_inside_change_restores_previous_state():
    b = _buffer()
    with pytest.raises(RuntimeError), b.change():
        b.data.append({"id": 99, "titel": "halb"})
        raise RuntimeError("Fehler mitten in der Aktion")
    assert b.find(99) is None and not b.can_undo


def test_undo_history_is_limited():
    b = _buffer()
    for i in range(MAX_UNDO_STEPS + 5):
        b.update(1, {"kommentar": str(i)})
    assert len(b.undo_stack) == MAX_UNDO_STEPS


def test_mark_saved_takes_new_ids_and_keeps_history():
    b = _buffer()
    b.add({"titel": "Neu"})
    saved = [dict(e, id=i) for i, e in enumerate(b.data, start=1)]
    b.mark_saved(saved)
    assert not b.dirty and b.can_undo and b.find(3)["titel"] == "Neu"


def test_titles_except_ignores_own_entry():
    b = _buffer()
    assert b.titles_except(1) == {"blue lock"}
    assert b.titles_except() == {"sanda", "blue lock"}


# ------------------------------------------------ VÖ-Abgleich (rote Werte)

class _Result:
    def __init__(self, entry_id, changes, previous):
        self.entry_id, self.changes, self.previous = entry_id, changes, previous


def test_apply_vlb_dates_writes_flags_and_is_one_undo_step():
    buf = _buffer()
    results = [
        _Result(1, {"voe_2": "13.01.2027"}, {"voe_2": ""}),
        _Result(2, {"voe_1": "05.03.2027"}, {"voe_1": "TBA"}),
    ]
    applied = buf.apply_vlb_dates(results)
    assert len(applied) == 2
    assert buf.find(1)["voe_2"] == "13.01.2027" and logic.new_value_columns(buf.find(1)) == ("voe_2",)
    assert buf.find(2)["voe_1"] == "05.03.2027" and logic.new_value_columns(buf.find(2)) == ("voe_1",)
    assert buf.dirty and len(buf.undo_stack) == 1
    buf.undo()
    assert not buf.dirty and buf.find(2)["voe_1"] == "TBA" and logic.NEW_VALUE_KEY not in buf.find(2)


def test_apply_vlb_dates_skips_fields_changed_in_the_meantime():
    buf = _buffer()
    buf.find(1)["voe_2"] = "von Hand"
    applied = buf.apply_vlb_dates([_Result(1, {"voe_2": "13.01.2027"}, {"voe_2": ""})])
    assert applied == [] and buf.find(1)["voe_2"] == "von Hand"
    assert not buf.can_undo or buf.undo_stack == []   # nichts geändert -> kein Rückgängig-Schritt


def test_apply_vlb_dates_ignores_unknown_entries():
    buf = _buffer()
    assert buf.apply_vlb_dates([_Result(99, {"voe_1": "01.01.2027"}, {"voe_1": ""})]) == []


def test_manual_edit_removes_flag_but_other_edits_keep_it():
    buf = _buffer()
    buf.apply_vlb_dates([_Result(1, {"voe_2": "13.01.2027", "voe_3": "13.04.2027"}, {"voe_2": "", "voe_3": ""})])
    buf.update(1, {"kommentar": "x", "voe_2": "13.01.2027", "voe_3": "20.04.2027"})   # voe_3 von Hand geändert
    assert logic.new_value_columns(buf.find(1)) == ("voe_2",)


def test_saving_clears_flags():
    buf = _buffer()
    buf.apply_vlb_dates([_Result(1, {"voe_2": "13.01.2027"}, {"voe_2": ""})])
    saved = [{k: v for k, v in e.items() if k != logic.NEW_VALUE_KEY} for e in buf.data]   # wie db.load_all()
    buf.mark_saved(saved)
    assert not buf.dirty and logic.new_value_columns(buf.find(1)) == ()

"""
library.py
Der Speicher-Puffer der Bibliothek: alle Einträge als Liste von Dicts, die
erst beim aktiven Speichern in die Datenbank geschrieben werden, dazu
Rückgängig/Wiederholen und alle Bearbeitungsaktionen.

Bewusst ohne Qt, damit sich die Logik direkt testen lässt - das Hauptfenster
(gui/main_window.py) ruft nur diese Methoden auf und kümmert sich um Anzeige,
Rückfragen und das Änderungsprotokoll.
"""

import copy
from contextlib import contextmanager
from typing import Optional

import logic
import order_mail

MAX_UNDO_STEPS = 50


class LibraryBuffer:
    def __init__(self, entries=None):
        self.load(entries or [])

    # ------------------------------------------------------ Laden/Speichern

    def load(self, entries) -> None:
        """Übernimmt einen frisch geladenen Bestand (Programmstart,
        Google-Drive-Download): gilt als gespeichert, Historie ist leer."""
        self.data = list(entries)
        self._clean = copy.deepcopy(self.data)
        self.next_temp_id = -1   # negative IDs für noch nicht gespeicherte, neue Einträge
        self.undo_stack = []
        self.redo_stack = []

    def mark_saved(self, entries) -> None:
        """Nach dem Speichern: der Puffer ist der gespeicherte Stand (mit den
        von der Datenbank neu vergebenen IDs). Die Historie bleibt erhalten."""
        self.data = list(entries)
        self._clean = copy.deepcopy(self.data)

    @property
    def dirty(self) -> bool:
        """Weicht der Puffer vom zuletzt geladenen/gespeicherten Stand ab?
        Echter Vergleich statt Flag: Wer per Rückgängig genau zum
        gespeicherten Stand zurückkehrt, hat keine ungespeicherten Änderungen."""
        return self.data != self._clean

    # ------------------------------------------------------------ Abfragen

    def find(self, row_id) -> Optional[dict]:
        return next((e for e in self.data if e.get("id") == row_id), None)

    def distinct_values(self, column) -> list:
        values = {(e.get(column) or "").strip() for e in self.data}
        values.discard("")
        return sorted(values, key=str.lower)

    def titles_except(self, row_id=None) -> set:
        """Alle Titel (klein, ohne Leerzeichen außen) außer dem von `row_id`
        - für die Prüfung auf doppelte Titel im Formular."""
        return {(e.get("titel") or "").strip().casefold() for e in self.data if e.get("id") != row_id}

    # ------------------------------------------------ Rückgängig/Wiederholen

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    @contextmanager
    def change(self):
        """
        Klammert eine Änderung am Puffer für Rückgängig:

            with buffer.change():
                ... self.data verändern ...

        Nur wenn sich der Puffer tatsächlich geändert hat, entsteht ein
        Rückgängig-Schritt und die Wiederholen-Historie wird verworfen. Eine
        abgelehnte Aktion (z.B. "+1" auf ungültige Zahl) lässt beide
        unangetastet. Bei einer Ausnahme wird der Stand vorher wiederhergestellt.
        """
        before = (copy.deepcopy(self.data), self.next_temp_id)
        try:
            yield
        except BaseException:
            self.data, self.next_temp_id = before
            raise
        if self.data != before[0]:
            self.undo_stack.append(before)
            del self.undo_stack[:-MAX_UNDO_STEPS]
            self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append((copy.deepcopy(self.data), self.next_temp_id))
        self.data, self.next_temp_id = self.undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append((copy.deepcopy(self.data), self.next_temp_id))
        self.data, self.next_temp_id = self.redo_stack.pop()
        return True

    # ------------------------------------------------------------ Aktionen

    def _new_id(self) -> int:
        new_id = self.next_temp_id
        self.next_temp_id -= 1
        return new_id

    def add(self, values: dict) -> dict:
        """Legt einen neuen Eintrag an und gibt ihn zurück."""
        with self.change():
            entry = dict(values, id=self._new_id())
            self.data.append(entry)
        return entry

    def update(self, row_id, values: dict) -> Optional[dict]:
        """Übernimmt geänderte Werte; erreichte Bestellt-/Angekommen-
        Markierungen entfallen dabei (siehe logic.clear_fulfilled_marks)."""
        with self.change():
            entry = self.find(row_id)
            if entry is not None:
                entry.update(values)
                logic.clear_fulfilled_marks(entry)
        return entry

    def delete(self, row_id) -> Optional[dict]:
        with self.change():
            entry = self.find(row_id)
            if entry is not None:
                self.data = [e for e in self.data if e.get("id") != row_id]
        return entry

    def increment_baende(self, row_id):
        """ "+1" auf "Bände (bis)" (siehe logic.increment_baende); entfernt
        danach erreichte Markierungen. Gibt den neuen Wert zurück, oder None
        bei ungültiger Zahl (dann bleibt alles unverändert)."""
        with self.change():
            entry = self.find(row_id)
            result = logic.increment_baende(entry) if entry is not None else None
            if result is not None:
                logic.clear_fulfilled_marks(entry)
        return result

    def increment_gelesen(self, row_id):
        """ "+1" auf "Gelesen bis" - Rückgabe wie logic.increment_gelesen."""
        with self.change():
            entry = self.find(row_id)
            result = logic.increment_gelesen(entry) if entry is not None else None
        return result

    def import_entries(self, parsed) -> tuple[int, int]:
        """Übernimmt CSV-Einträge, deren Titel noch nicht vorkommt. Gibt
        (importiert, übersprungen) zurück."""
        imported = skipped = 0
        with self.change():
            existing = self.titles_except()
            for values in parsed:
                key = (values.get("titel") or "").strip().casefold()
                if key in existing:
                    skipped += 1
                    continue
                self.data.append(dict(values, id=self._new_id()))
                existing.add(key)
                imported += 1
        return imported, skipped

    def apply_order_matches(self, matches) -> list:
        """Setzt die Bestellt-/Angekommen-Markierungen aus order_mail.
        match_items() (Wert = Bandnummer) und gibt die Treffer zurück, die
        tatsächlich etwas geändert haben (siehe order_mail.new_marks)."""
        new = order_mail.new_marks(matches)
        with self.change():
            for m in new:
                m.entry[order_mail.FLAG_FIELD[m.item.kind]] = str(m.band)
        return new

    def clear_marks(self, row_id) -> Optional[dict]:
        """Entfernt beide Markierungen eines Eintrags von Hand."""
        with self.change():
            entry = self.find(row_id)
            if entry is not None:
                entry["bestellt"] = ""
                entry["angekommen"] = ""
        return entry

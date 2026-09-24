"""
models.py
Formales Datenmodell für einen Bibliothekseintrag: `Werk`, eine dataclass
mit denselben Feldern wie database.COLUMN_NAMES (+ id), dynamisch aus
database.COLUMN_NAMES erzeugt - eine zweite, unabhängig zu pflegende
Feldliste (die mit der Zeit auseinanderdriften könnte) wird damit
vermieden, ganz wie import_csv.CSV_FIELDS es bereits für den CSV-Import
macht.

Werk ist bewusst dict-kompatibel (get/__getitem__/__setitem__/keys/items/
update): der komplette Speicher-Puffer in gui.py, logic.py und
isbn_lookup.py arbeitet aktuell mit einfachen Dicts (`entry.get("titel")`,
`entry["baende_bis"] = ...` usw.) an hunderten Stellen. Werk lässt sich
darum schon jetzt als Drop-in-Ersatz für ein solches Dict verwenden, ohne
dass jede einzelne Stelle sofort umgeschrieben werden müsste - eine
vollständige Umstellung des Puffers von dict auf Werk ist eine separate,
größere Aufgabe mit entsprechend höherem Änderungsumfang und wurde bewusst
NICHT in einem Zug mit dieser Vorbereitung erledigt (Risiko einer
Destabilisierung des aktuell fehlerfrei laufenden Programms). Neuer Code
kann Werk schon heute direkt verwenden, z.B.:

    werk = Werk.from_dict(row_dict)
    werk.baende_bis  # statt werk["baende_bis"] oder werk.get("baende_bis")
    werk.to_dict()    # zurück zu einem normalen Dict, z.B. für db.replace_all()
"""

from dataclasses import dataclass, field, fields, make_dataclass
from typing import Optional

import database as db


class _DictLikeMixin:
    """Macht eine dataclass-Instanz von außen wie ein Dict benutzbar -
    für Drop-in-Kompatibilität mit dem bestehenden, dict-basierten Code."""

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __contains__(self, key):
        return hasattr(self, key)

    def keys(self):
        return [f.name for f in fields(self)]

    def items(self):
        return [(f.name, getattr(self, f.name)) for f in fields(self)]

    def values(self):
        return [getattr(self, f.name) for f in fields(self)]

    def update(self, other: dict):
        """Wie dict.update(): übernimmt jeden Schlüssel aus `other`, der
        ein bekanntes Feld ist. Unbekannte Schlüssel werden (wie bei einem
        echten Dict eigentlich nicht üblich, hier aber bewusst tolerant für
        den Übergang) still ignoriert statt eine Exception auszulösen."""
        known = {f.name for f in fields(self)}
        for k, v in other.items():
            if k in known:
                setattr(self, k, v)

    def to_dict(self) -> dict:
        return dict(self.items())

    @classmethod
    def from_dict(cls, data: dict) -> "Werk":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# Felder dynamisch aus database.COLUMN_NAMES erzeugen (Reihenfolge: id
# zuerst, dann die regulären Spalten in derselben Reihenfolge wie in der
# Datenbank/GUI) - einzige Quelle der Wahrheit bleibt database.py.
_FIELDS = [("id", Optional[int], field(default=None))] + [
    (col, str, field(default="")) for col in db.COLUMN_NAMES
]

Werk = make_dataclass("Werk", _FIELDS, bases=(_DictLikeMixin,))
Werk.__doc__ = (
    "Ein einzelner Bibliothekseintrag - Felder entsprechen 1:1 "
    "database.COLUMN_NAMES (+ id). Dict-kompatibel, siehe models.py-Modul-"
    "Docstring."
)

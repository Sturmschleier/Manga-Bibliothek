"""
gui/ - Grafische Oberfläche (PySide6/Qt) der Manga/Light-Novel-Bibliothek.

Aufgeteilt in:

    constants.py   - geteilte Konstanten/Hilfsfunktionen (kein Qt-Code)
    table.py       - MangaTableModel, CellDelegate
    dialogs.py     - EntryDialog, ConfigDialog, IsbnLookupDialog
    mail_dialogs.py - MailSettingsDialog, MailSelectDialog (Postfach-Abruf)
    isbn_view.py   - IsbnResultWindow
    worker.py      - AsyncCall (Hintergrund-Aufgaben mit Qt-Signalen)
    main_window.py - MangaLibraryApp (Hauptfenster)

Der Speicher-Puffer mit Rückgängig/Wiederholen liegt Qt-frei in library.py.

Re-exportiert die wichtigsten Namen hier, damit `from gui import
MangaLibraryApp` (z.B. in main.py) unverändert funktioniert - das reine
Aufteilen einer Datei in ein Paket soll für Aufrufer keinen sichtbaren
Unterschied machen.
"""

from .constants import (
    APP_TITLE,
    COL_DEFAULT_WIDTHS,
    DISPLAY_COLUMNS,
    DISPLAY_LABELS,
    INCREMENTABLE_COLUMNS,
    JA_NEIN_OPTIONEN,
    PLUS_BTN_MARGIN,
    PLUS_BTN_WIDTH,
    ROW_ID_ROLE,
    RUCKSTAND_COLUMN,
    TYP_OPTIONEN,
    VOE1_FILTER_OPTIONS,
    VOE_COLUMNS,
)
from .dialogs import ConfigDialog, EntryDialog, IsbnLookupDialog
from .isbn_view import IsbnResultWindow
from .main_window import MangaLibraryApp
from .table import CellDelegate, MangaTableModel

__all__ = [
    "APP_TITLE",
    "COL_DEFAULT_WIDTHS",
    "DISPLAY_COLUMNS",
    "DISPLAY_LABELS",
    "INCREMENTABLE_COLUMNS",
    "JA_NEIN_OPTIONEN",
    "PLUS_BTN_MARGIN",
    "PLUS_BTN_WIDTH",
    "ROW_ID_ROLE",
    "RUCKSTAND_COLUMN",
    "TYP_OPTIONEN",
    "VOE1_FILTER_OPTIONS",
    "VOE_COLUMNS",
    "CellDelegate",
    "ConfigDialog",
    "EntryDialog",
    "IsbnLookupDialog",
    "IsbnResultWindow",
    "MangaLibraryApp",
    "MangaTableModel",
]

"""
paths.py
Ermittelt das Verzeichnis, in dem Datendateien (Datenbank, Google-
Zugangsdaten) abgelegt werden.

Wichtig für die spätere .exe: Wird die Anwendung mit PyInstaller (--onefile)
gebündelt, zeigt `__file__` zur Laufzeit auf einen temporären
Entpackungsordner, der nach dem Beenden wieder gelöscht wird. Damit die
Datenbank und die Google-Zugangsdaten dauerhaft neben der .exe erhalten
bleiben, wird in diesem Fall stattdessen der Ordner von `sys.executable`
verwendet.
"""

import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Als PyInstaller-exe gebündelt: Ordner der .exe-Datei verwenden
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

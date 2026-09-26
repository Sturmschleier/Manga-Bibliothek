"""
main.py
Einstiegspunkt: startet die Manga & Light Novel Bibliothek (Qt/PySide6).

Aufruf:
    python main.py
"""

import sys
import traceback

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

import changelog
import database as db
from gui import APP_TITLE, MangaLibraryApp


def _install_excepthook():
    """Zeigt unerwartete Fehler als Dialog an und schreibt sie nach
    LOG/fehler.log. In der exe (ohne Konsole) gingen sie sonst unbemerkt
    verloren."""

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            log_path = changelog.log_error(details)
            if sys.__stderr__ is not None:
                sys.__excepthook__(exc_type, exc_value, exc_tb)
            if QApplication.instance() is None:
                return
            text = f"Ein unerwarteter Fehler ist aufgetreten:\n\n{exc_type.__name__}: {exc_value}"
            if log_path:
                text += f"\n\nDetails stehen in:\n{log_path}"
            box = QMessageBox(QMessageBox.Critical, APP_TITLE, text, QMessageBox.Ok)
            box.setDetailedText(details)
            box.exec()
        except Exception:  # noqa: BLE001 - der Fehler-Handler selbst darf nicht abstürzen
            pass

    sys.excepthook = hook


def _acquire_instance_lock():
    """Verhindert, dass das Programm zweimal gleichzeitig läuft: Beide
    Fenster hätten sonst einen eigenen Zwischenspeicher, und wer zuletzt
    speichert, würde die Änderungen des anderen still überschreiben.

    Gibt die gehaltene Sperre zurück (muss bis Programmende referenziert
    bleiben), oder None, wenn bereits ein anderes Programmfenster läuft.
    Eine Sperre eines abgestürzten Programms wird automatisch übernommen."""
    lock = QLockFile(str(db.DB_FILE) + ".lock")
    # 0 = nie allein wegen ihres Alters als verwaist gelten (das Programm
    # läuft oft stundenlang), sondern nur, wenn der sperrende Prozess fehlt.
    lock.setStaleLockTime(0)
    if lock.tryLock(100) or lock.error() != QLockFile.LockFailedError:
        # Andere Fehler (z.B. keine Schreibrechte im Ordner) sollen den
        # Start nicht verhindern.
        return lock
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    _install_excepthook()

    lock = _acquire_instance_lock()
    if lock is None:
        QMessageBox.warning(
            None, APP_TITLE,
            "Die Bibliothek ist bereits in einem anderen Programmfenster geöffnet.\n\n"
            "Bitte das bereits geöffnete Fenster verwenden – ein zweites würde beim Speichern "
            "die Änderungen des ersten überschreiben.",
        )
        sys.exit(1)

    window = MangaLibraryApp()
    window.show()
    exit_code = app.exec()
    lock.unlock()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

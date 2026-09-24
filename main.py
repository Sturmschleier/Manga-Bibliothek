"""
main.py
Einstiegspunkt: startet die Manga & Light Novel Bibliothek (Qt/PySide6).

Aufruf:
    python main.py
"""

import sys

from PySide6.QtWidgets import QApplication

from gui import MangaLibraryApp


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Manga & Light Novel Bibliothek")
    window = MangaLibraryApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

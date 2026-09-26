"""
gui/worker.py
AsyncCall: führt eine langsame Aufgabe (Netzwerk, Google Drive, ISBN-
Abgleich) in einem Hintergrund-Thread aus, damit die Oberfläche bedienbar
bleibt, und meldet Ergebnis und Fortschritt als Qt-Signale im Haupt-Thread.
"""

import threading

from PySide6.QtCore import QObject, Signal


class AsyncCall(QObject):
    """Führt `func()` in einem Hintergrund-Thread aus und meldet das Ergebnis
    über `finished(result, error)` im Haupt-Thread (Qt stellt Signale aus
    anderen Threads automatisch sicher zu). `func` kann über
    `call.progress.emit(erledigt, gesamt, text)` Fortschritt melden.
    Das Objekt muss vom Aufrufer referenziert bleiben, bis das Signal
    angekommen ist (z.B. über ein Elternobjekt)."""

    finished = Signal(object, object)   # result, error (Exception oder None)
    progress = Signal(int, int, str)    # erledigt, gesamt, text

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self._func = func

    def start(self):
        def worker():
            result, error = None, None
            try:
                result = self._func()
            except Exception as exc:  # noqa: BLE001 - wird dem Nutzer angezeigt
                error = exc
            self.finished.emit(result, error)

        threading.Thread(target=worker, daemon=True).start()

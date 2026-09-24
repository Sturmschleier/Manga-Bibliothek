"""
conftest.py
Sorgt dafür, dass die Module im Projektwurzelverzeichnis (logic.py,
sorting.py, isbn_lookup.py, import_csv.py, ...) beim Testlauf importierbar
sind, unabhängig davon, aus welchem Verzeichnis `pytest` aufgerufen wird.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

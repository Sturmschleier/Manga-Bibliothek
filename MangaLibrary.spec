# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Bauanleitung für MangaLibrary.exe - die einzige Stelle, an der
# festgelegt ist, was in die exe kommt. build.bat (und ein lokales
# Build_work.bat) rufen nur "pyinstaller MangaLibrary.spec" auf.
#
# Bewusst schlank:
# - PySide6 wird NICHT komplett eingepackt (früher "--collect-all PySide6",
#   ca. 660 MB inkl. Web-Engine, 3D, Multimedia ...). PyInstallers eigene
#   PySide6-Regeln übernehmen nur die tatsächlich importierten Qt-Module
#   (QtCore, QtGui, QtWidgets) samt der nötigen Plugins.
# - Von den über 500 Google-API-Beschreibungen (ca. 100 MB) wird nur die für
#   Google Drive v3 gebraucht (drive_sync.py: build("drive", "v3")).

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = collect_data_files("googleapiclient", includes=["discovery_cache/documents/drive.v3.json"])
binaries = []
hiddenimports = [
    "google_auth_httplib2",       # einzelnes Modul, wird von googleapiclient nur bei Bedarf geladen
    "keyring.backends.Windows",   # Windows-Anmeldeinformationen für das IMAP-Passwort (mail_fetch.py)
]
package_datas, package_binaries, package_hiddenimports = collect_all("google_auth_oauthlib")
datas += package_datas
binaries += package_binaries
hiddenimports += package_hiddenimports

# Qt-Module, die das Programm nicht nutzt - falls eine installierte Bibliothek
# sie indirekt anzieht, sollen sie trotzdem nicht in die exe
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql",
    "tkinter",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MangaLibrary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,   # UPX-komprimierte Qt-DLLs können defekt sein und lösen oft Virenscanner-Fehlalarme aus
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # Fensteranwendung ohne Konsolenfenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

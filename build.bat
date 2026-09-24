@echo off
REM build.bat
REM Erstellt eine eigenstaendige MangaLibrary.exe (Windows) mit PyInstaller.
REM Muss auf einem Windows-Rechner mit installiertem Python ausgefuehrt werden
REM (PyInstaller kann nicht "fuer Windows" von einem anderen Betriebssystem
REM aus bauen - die exe muss auf Windows selbst entstehen).

python -m pip install -r requirements.txt
python -m pip install pyinstaller

python -m PyInstaller --noconfirm --onefile --windowed --name "MangaLibrary" ^
    --collect-all PySide6 ^
    --collect-all googleapiclient ^
    --collect-all google_auth_oauthlib ^
    --collect-all google_auth_httplib2 ^
    --hidden-import googleapiclient.discovery_cache.file ^
    main.py

echo.
echo Fertig! Die Datei dist\MangaLibrary.exe ist eigenstaendig.
echo Wichtig: manga_library.db, credentials.json und token.json legen sich
echo automatisch NEBEN die exe - also die exe nicht isoliert verschieben,
echo sondern immer aus ihrem eigenen Ordner heraus starten.
pause

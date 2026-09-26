@echo off
REM build.bat
REM Baut MangaLibrary.exe (Windows) mit PyInstaller - reproduzierbar:
REM   - in einer eigenen Build-Umgebung .venv-build (unabhaengig davon, was im
REM     globalen Python installiert ist)
REM   - mit exakt festgelegten Versionen aus requirements-build.txt
REM   - nach der Bauanleitung MangaLibrary.spec (dort steht, was in die exe kommt)
REM
REM Aufruf:   build.bat              wartet am Ende auf einen Tastendruck
REM           build.bat --no-pause   z.B. aus einem anderen Skript heraus
REM Ergebnis: dist\MangaLibrary.exe
REM
REM Muss auf Windows laufen (eine Windows-exe laesst sich nicht von einem
REM anderen Betriebssystem aus bauen).

setlocal
cd /d "%~dp0"
set "VENV=.venv-build"

if not exist "%VENV%\Scripts\python.exe" (
    echo Lege die Build-Umgebung %VENV% an ...
    python -m venv "%VENV%" || goto :fehler
)

echo Installiere die festgelegten Versionen aus requirements-build.txt ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements-build.txt || goto :fehler

echo Baue MangaLibrary.exe ...
"%VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean MangaLibrary.spec || goto :fehler

echo.
echo Fertig! dist\MangaLibrary.exe ist eigenstaendig.
echo Wichtig: manga_library.db, config.json, credentials.json und token.json legen sich
echo automatisch NEBEN die exe - die exe also nicht isoliert verschieben,
echo sondern immer aus ihrem eigenen Ordner heraus starten.
if /i not "%~1"=="--no-pause" pause
exit /b 0

:fehler
echo.
echo FEHLER: Der Build ist fehlgeschlagen (siehe Meldungen oben).
if /i not "%~1"=="--no-pause" pause
exit /b 1

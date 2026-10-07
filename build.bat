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

if exist "%VENV%\Scripts\python.exe" goto :venv_vorhanden
call :suche_python || goto :fehler
echo Lege die Build-Umgebung %VENV% an ...
%PY% -m venv "%VENV%" || goto :fehler
:venv_vorhanden

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

:suche_python
REM Findet ein echtes Python. Die Microsoft-Store-Verknuepfung "python.exe" in
REM WindowsApps zaehlt nicht: sie meldet nur "Python wurde nicht gefunden",
REM wenn Python gar nicht installiert ist.
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
    py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
)
if defined PY exit /b 0
echo.
echo FEHLER: Python ist nicht installiert (oder nicht im PATH).
echo Zum Bauen wird Python 3.9 oder neuer benoetigt:
echo   1. Von https://www.python.org/downloads/ installieren und im Installer
echo      "Add python.exe to PATH" ankreuzen.
echo   2. Dieses Fenster schliessen und build.bat erneut starten.
echo Die Store-Verknuepfung "python" allein reicht nicht. Zum reinen Starten der
echo fertigen MangaLibrary.exe aus dem Release wird kein Python benoetigt.
exit /b 1

:fehler
echo.
echo FEHLER: Der Build ist fehlgeschlagen (siehe Meldungen oben).
if /i not "%~1"=="--no-pause" pause
exit /b 1

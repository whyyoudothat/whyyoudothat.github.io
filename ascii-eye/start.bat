@echo off
rem Startet die ASCII-Animation. Fenster bleibt bei einem Fehler offen.
cd /d "%~dp0"

set PY=python
where py >nul 2>nul && set PY=py

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden.
    echo Bitte Python von https://www.python.org/downloads/ installieren
    echo und beim Setup den Haken bei "Add python.exe to PATH" setzen.
    pause
    exit /b 1
)

%PY% -c "import numpy" >nul 2>nul
if errorlevel 1 (
    echo Installiere numpy ...
    %PY% -m pip install numpy
)

%PY% main.py
if errorlevel 1 (
    echo.
    echo Das Skript wurde mit einem Fehler beendet. Die Meldung steht oben.
    pause
)

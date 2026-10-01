@echo off
rem Synchronise les donnees Garmin dans jgarmin.db (dossier du projet).
rem Usage : double-clic, ou jgarmin-sync.bat --full pour relire les 12 derniers mois.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\jgarmin.exe" (
    echo Environnement introuvable dans %~dp0.venv
    echo Installe-le d abord :
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -e .
    pause
    exit /b 1
)

set "TOKENS=%JGARMIN_TOKENS%"
if "%TOKENS%"=="" set "TOKENS=%USERPROFILE%\.jgarmin\tokens"
if not exist "%TOKENS%\garmin_tokens.json" (
    echo Pas encore de session Garmin sur ce PC : connexion d abord.
    ".venv\Scripts\jgarmin.exe" login
    if errorlevel 1 goto fin
    echo.
)

".venv\Scripts\jgarmin.exe" sync %*
if errorlevel 1 (
    echo.
    echo La synchro s est arretee. Si la session a expire, relance ce fichier apres :
    echo   .venv\Scripts\jgarmin login
)

:fin
echo.
pause

@echo off
rem Lance l interface JGarminTracker et ouvre le navigateur. Ctrl+C pour arreter le serveur.
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

rem Ouvre le navigateur 2 secondes apres le demarrage du serveur.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5002"
".venv\Scripts\jgarmin.exe" serve --port 5002
pause

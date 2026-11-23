@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
echo Installation des dependances...
%PY% -m pip install -q -r requirements.txt
echo Lancement de Scout...
%PY% app.py
pause

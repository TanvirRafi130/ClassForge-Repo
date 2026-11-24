@echo off
cd /d "%~dp0"
echo Setting up ClassForge...
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist ".profile" copy .profile.example .profile
echo.
echo Done. Edit .profile to pick a notes engine, then run run.bat

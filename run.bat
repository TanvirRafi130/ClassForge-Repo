@echo off
cd /d "%~dp0"
if not exist ".venv" (
  echo No .venv found - run setup.bat first.
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Starting ClassForge at http://127.0.0.1:8080
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080

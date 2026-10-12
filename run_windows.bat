@echo off
cd /d "%~dp0"
if not exist .env (
  copy .env.example .env
  echo Add your Telegram token and chat ID to .env, save it, then run this file again.
  notepad .env
  pause
  exit /b
)
python -m pip install -r requirements.txt
python bot.py
pause

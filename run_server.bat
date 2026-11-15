@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
echo.
echo Open http://localhost:8000 in your browser
py -m uvicorn api:app --port 8000
pause

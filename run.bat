@echo off
echo Starting Intelligent Traffic Safety System...

echo Starting Backend API...
cd backend
start cmd /k ".\venv\Scripts\activate && python main.py"

echo Opening Frontend Dashboard...
cd ..\frontend
start index.html

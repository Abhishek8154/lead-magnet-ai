@echo off
title Lead Magnet AI - Command Dashboard
echo ============================================================
echo      LEAD MAGNET AI - SYSTEM LAUNCHER
echo ============================================================
echo Starting Command Dashboard Server...

cd /d "%~dp0"

:: Start Main Web Dashboard on Port 8001 in background
start /min "Lead Magnet Web Dashboard" python web/app.py

:: Open browser automatically
start http://127.0.0.1:8001

echo ============================================================
echo [SUCCESS] System started! Dashboard active at http://127.0.0.1:8001
echo ============================================================
exit


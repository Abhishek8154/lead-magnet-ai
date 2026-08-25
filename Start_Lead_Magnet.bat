@echo off
title Lead Magnet AI - 1-Click System Launcher
echo ============================================================
echo      LEAD MAGNET AI - AUTOMATED LAUNCHER
echo ============================================================
echo Starting Demo Server and Command Dashboard...

cd /d "%~dp0"

:: Start Cloudflare Public Tunnel and Demo Server
start /min "Lead Magnet Public Tunnel" python demo/tunnel.py

:: Start Main Web Dashboard on Port 8001 in background
start /min "Lead Magnet Web Dashboard" python web/app.py

:: Wait 3 seconds for servers to initialize
timeout /t 3 /nobreak >nul

:: Open browser automatically
start http://127.0.0.1:8001

echo ============================================================
echo [SUCCESS] System started! Live Public Tunnel & Dashboard active.
echo ============================================================
exit


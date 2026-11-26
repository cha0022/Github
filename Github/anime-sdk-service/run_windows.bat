@echo off
REM FLOW NOTE: Checks Node, installs the SDK package if missing, then starts the Anime-SDK bridge on its configured port.
REM DEBUG NOTE: One-click launcher for the local Anime-SDK bridge.
cd /d "%~dp0"
where node >nul 2>nul || (echo Node.js 20 or newer is required. & pause & exit /b 1)
if not defined ANIME_SDK_PORT set "ANIME_SDK_PORT=3000"
if not defined ANIME_SDK_PUBLIC_PROXY_BASE set "ANIME_SDK_PUBLIC_PROXY_BASE=http://127.0.0.1:5000/proxy"
if not exist "node_modules\anime-sdk" (
  echo First-time setup: installing Anime-SDK...
  call npm install
  if errorlevel 1 (pause & exit /b 1)
)
call npm start
pause

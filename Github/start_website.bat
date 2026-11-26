@echo off
REM FLOW NOTE: Checks Python and Node, prepares Anime-SDK, then starts Anime-SDK and Flask in separate windows.
setlocal
set "PROJECT_ROOT=%~dp0"
if not defined SITE_PORT set "SITE_PORT=5000"
if not defined SDK_PORT set "SDK_PORT=3000"

where python >nul 2>nul || (echo Python was not found in PATH. Install Python 3.10 or newer. & pause & exit /b 1)
where node >nul 2>nul || (echo Node.js was not found in PATH. Install Node.js 20 or newer. & pause & exit /b 1)

if not exist "%PROJECT_ROOT%anime-sdk-service\node_modules\anime-sdk" (
  echo Installing Anime-SDK dependencies for the first run...
  pushd "%PROJECT_ROOT%anime-sdk-service"
  call npm install
  if errorlevel 1 (popd & pause & exit /b 1)
  popd
)

start "Anime-SDK service - port %SDK_PORT%" /D "%PROJECT_ROOT%anime-sdk-service" cmd /k "set ANIME_SDK_PORT=%SDK_PORT%&& set ANIME_SDK_PUBLIC_PROXY_BASE=http://127.0.0.1:%SITE_PORT%/proxy&& npm start"
timeout /t 2 /nobreak >nul
start "HIANIME website - port %SITE_PORT%" /D "%PROJECT_ROOT%" cmd /k "set ANIME_SDK_URL=http://127.0.0.1:%SDK_PORT%&& set ANIME_SDK_PUBLIC_PROXY_BASE=http://127.0.0.1:%SITE_PORT%/proxy&& python -m flask --app app run --host 127.0.0.1 --port %SITE_PORT% --no-debugger --no-reload"

echo Starting HIANIME and Anime-SDK in separate windows.
echo Website: http://127.0.0.1:%SITE_PORT%
echo SDK: http://127.0.0.1:%SDK_PORT%
echo Set SITE_PORT or SDK_PORT before launching to choose other ports.
endlocal


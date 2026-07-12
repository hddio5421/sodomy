@echo off
setlocal

cd /d "%~dp0"
set "PORT=8358"
set "URL=http://127.0.0.1:%PORT%/web/"
set "PYTHON=C:\Users\Ernesto\miniconda3\python.exe"

if not exist "%PYTHON%" (
  echo Python not found: %PYTHON%
  pause
  exit /b 1
)

powershell -NoProfile -Command "$port = %PORT%; if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','http.server','%PORT%' -WorkingDirectory '%CD%' -WindowStyle Hidden }"
if errorlevel 1 (
  echo Failed to start the web server.
  pause
  exit /b 1
)

powershell -NoProfile -Command "$url = '%URL%'; for ($i = 0; $i -lt 20; $i++) { try { $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 250 }; exit 1"
if errorlevel 1 (
  echo The web page did not respond: %URL%
  pause
  exit /b 1
)

start "" "%URL%"
endlocal

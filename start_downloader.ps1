$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path logs | Out-Null
$arguments = @(
  "src\run_downloader.py",
  "--start", "2000-01-01",
  "--end", "2026-07-10",
  "--retry-minutes", "65",
  "--sleep", "0.15"
)
$process = Start-Process -FilePath python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
"Started FinMind downloader. PID=$($process.Id). Log=$PSScriptRoot\logs\finmind_downloader.log"

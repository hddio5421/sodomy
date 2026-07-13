$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path logs | Out-Null

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$minicondaPython = "C:\Users\Ernesto\miniconda3\python.exe"
if (Test-Path $venvPython) {
  $python = $venvPython
} elseif (Test-Path $minicondaPython) {
  $python = $minicondaPython
} else {
  $python = (Get-Command python -ErrorAction Stop).Source
}

$arguments = @(
  "src\run_downloader.py",
  "--end", "auto",
  "--batch-size", "550",
  "--sleep", "0.15"
)
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
"Started FinMind downloader. PID=$($process.Id). Log=$PSScriptRoot\logs\finmind_downloader.log"

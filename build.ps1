$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& .\sensor_host\build.ps1
if (-not (Test-Path .\sensor_host\bin\SkyLyricsSensors.exe)) { throw 'Sensor worker is missing' }
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --name SkyLyrics --icon assets/app.ico --add-data "assets;assets" --add-data "apply_update.ps1;." --add-data "sensor_host/bin;sensor_host" --collect-all winrt --hidden-import pystray._win32 --distpath dist tray.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }

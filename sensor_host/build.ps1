param([string]$DependencyArchive = '')
$ErrorActionPreference = 'Stop'
$sensorRoot = $PSScriptRoot
$cachePath = Join-Path $sensorRoot 'cache'
$binPath = Join-Path $sensorRoot 'bin'
New-Item -ItemType Directory -Force $cachePath, $binPath | Out-Null
if (-not $DependencyArchive) {
    $DependencyArchive = Join-Path $cachePath 'LibreHardwareMonitor-0.9.6.zip'
    if (-not (Test-Path -LiteralPath $DependencyArchive)) {
        Invoke-WebRequest 'https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip' -OutFile $DependencyArchive
    }
}
$expectedHash = '086D9F1B5A99E643EDC2CFAAAC16051685B551E4C5AC0B32A57C58C0E529C001'
if ((Get-FileHash -LiteralPath $DependencyArchive -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'LibreHardwareMonitor archive checksum mismatch'
}
$libraryPath = Join-Path $cachePath 'lhm-0.9.6'
Expand-Archive -LiteralPath $DependencyArchive -DestinationPath $libraryPath -Force
# CPU library dependencies only. Do not bundle the monitor UI or its task scheduler.
Get-ChildItem -LiteralPath $libraryPath -Filter '*.dll' | Where-Object {
    $_.Name -notmatch '^(Aga\.|OxyPlot|Microsoft\.Win32\.TaskScheduler)'
} | Copy-Item -Destination $binPath -Force
Copy-Item -LiteralPath (Join-Path $libraryPath 'LibreHardwareMonitor.exe.config') -Destination (Join-Path $binPath 'SkyLyricsSensors.exe.config') -Force
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:winexe /platform:x64 "/out:$binPath\SkyLyricsSensors.exe" "/reference:$binPath\LibreHardwareMonitorLib.dll" "$sensorRoot\SensorHost.cs"
if ($LASTEXITCODE -ne 0) { throw 'Sensor worker compilation failed' }
$manifest = Join-Path $cachePath 'sensor-files.txt'
$entries = Get-ChildItem -LiteralPath $binPath -File | Where-Object { $_.Extension -eq '.dll' -or $_.Name -in @('SkyLyricsSensors.exe','SkyLyricsSensors.exe.config') } | Sort-Object Name | ForEach-Object {
    (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + ' ' + $_.Name
}
[IO.File]::WriteAllLines($manifest, $entries, [Text.Encoding]::ASCII)
& $compiler /nologo /target:winexe /platform:x64 /reference:Microsoft.CSharp.dll /reference:System.Windows.Forms.dll "/resource:$manifest,sensor-files.txt" "/out:$binPath\SkyLyricsSensorSetup.exe" "$sensorRoot\SensorSetup.cs"
if ($LASTEXITCODE -ne 0) { throw 'Sensor setup compilation failed' }
Write-Output "Sensor worker built in $binPath"

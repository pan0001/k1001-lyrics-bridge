$ErrorActionPreference = 'Stop'
$folder = [IO.Path]::GetFullPath($PSScriptRoot)
$plan = Get-Content -LiteralPath (Join-Path $folder 'plan.json') -Raw | ConvertFrom-Json
$target = [IO.Path]::GetFullPath($plan.target)
$parent = Split-Path -Parent $folder
if ((Split-Path -Leaf $folder) -notmatch '^\.sky-update-[a-f0-9]{32}$' -or
    (Split-Path -Parent $target) -ne $parent -or $target -eq $folder) { exit 2 }
$new = Join-Path $folder 'new'
$backup = Join-Path $folder 'previous'
$ready = Join-Path $folder 'ready'
$exe = Join-Path $target 'SkyLyrics.exe'
$moved = $false
$installed = $false
$child = $null
try {
    # Only wait for the requesting application; never kill another instance.
    $old = Get-Process -Id $plan.parent_pid -ErrorAction SilentlyContinue
    if ($old -and -not $old.WaitForExit(60000)) { throw 'Application did not exit' }
    if (-not (Test-Path -LiteralPath (Join-Path $new 'SkyLyrics.exe'))) { throw 'Missing staged application' }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try { Move-Item -LiteralPath $target -Destination $backup; $moved = $true; break }
        catch { if ($attempt -eq 19) { throw }; Start-Sleep -Milliseconds 500 }
    }
    Move-Item -LiteralPath $new -Destination $target
    $installed = $true
    $env:SKYLYRICS_UPDATE_READY = $ready
    $child = Start-Process -FilePath $exe -ArgumentList '--background' -WorkingDirectory $target -WindowStyle Hidden -PassThru
    Remove-Item Env:SKYLYRICS_UPDATE_READY
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-Path -LiteralPath $ready) { $healthy = $true; break }
        if ($child.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $healthy) { throw 'Updated application did not become ready' }
    @{ok=$true; version=$plan.version; message='更新已安装'; backup=$backup} | ConvertTo-Json | Set-Content -LiteralPath $plan.status -Encoding UTF8
    # Keep one complete backup in this transaction folder for manual recovery.
} catch {
    $reason = $_.Exception.Message
    try {
        if ($child -and -not $child.HasExited) { Stop-Process -Id $child.Id -Force; $child.WaitForExit(5000) | Out-Null }
        if ($installed) { Move-Item -LiteralPath $target -Destination (Join-Path $folder 'failed') }
        if ($moved) { Move-Item -LiteralPath $backup -Destination $target }
        @{ok=$false; message="更新失败，已恢复旧版：$reason"} | ConvertTo-Json | Set-Content -LiteralPath $plan.status -Encoding UTF8
        Remove-Item Env:SKYLYRICS_UPDATE_READY -ErrorAction SilentlyContinue
        Start-Process -FilePath $exe -ArgumentList '--background' -WorkingDirectory $target -WindowStyle Hidden
    } catch {
        @{ok=$false; message="更新失败，请从更新目录恢复 previous 文件夹：$reason"} | ConvertTo-Json | Set-Content -LiteralPath $plan.status -Encoding UTF8
    }
    exit 1
}

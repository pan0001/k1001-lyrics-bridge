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

function Write-UpdateResult($value) {
    # Reporting is best effort; a locked status file must not undo a healthy update.
    try { $value | ConvertTo-Json | Set-Content -LiteralPath $plan.status -Encoding UTF8 }
    catch { Write-Warning ('Could not save update result: ' + $_.Exception.Message) }
}

function Test-PlainDirectoryTree([string]$root) {
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($root)
    while ($pending.Count -gt 0) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
            if ($item.PSIsContainer) { $pending.Push($item.FullName) }
        }
    }
    return $true
}

function Remove-OlderCompletedUpdates {
    # Keep this transaction's backup. Failed and unfinished transactions remain recoverable.
    foreach ($candidate in Get-ChildItem -LiteralPath $parent -Directory -Force) {
        try {
            $candidatePath = [IO.Path]::GetFullPath($candidate.FullName)
            if ($candidatePath -eq $folder -or $candidate.Name -notmatch '^\.sky-update-[a-f0-9]{32}$' -or
                (Split-Path -Parent $candidatePath) -ne $parent -or
                ($candidate.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
            $receiptPath = Join-Path $candidatePath 'completed.json'
            if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { continue }
            # Never recursively remove a transaction containing a junction or symbolic link.
            if (-not (Test-PlainDirectoryTree $candidatePath)) { continue }
            $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
            if ($receipt.ok -ne $true -or [IO.Path]::GetFullPath($receipt.target) -ne $target) { continue }
            Remove-Item -LiteralPath $candidatePath -Recurse -Force
        } catch { Write-Warning ('Could not remove old update backup: ' + $_.Exception.Message) }
    }
}

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
} catch {
    $reason = $_.Exception.Message
    try {
        if ($child -and -not $child.HasExited) { Stop-Process -Id $child.Id -Force; $child.WaitForExit(5000) | Out-Null }
        if ($installed) { Move-Item -LiteralPath $target -Destination (Join-Path $folder 'failed') }
        if ($moved) { Move-Item -LiteralPath $backup -Destination $target }
        Write-UpdateResult @{ok=$false; message="更新失败，已恢复旧版：$reason"}
        Remove-Item Env:SKYLYRICS_UPDATE_READY -ErrorAction SilentlyContinue
        Start-Process -FilePath $exe -ArgumentList '--background' -WorkingDirectory $target -WindowStyle Hidden
    } catch {
        Write-UpdateResult @{ok=$false; message="更新失败，请从更新目录恢复 previous 文件夹：$reason"}
    }
    exit 1
}

# Only a completed, healthy transaction is eligible for later backup cleanup.
Write-UpdateResult @{ok=$true; version=$plan.version; message='更新已安装'; backup=$backup}
try {
    @{ok=$true; target=$target; version=$plan.version} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $folder 'completed.json') -Encoding UTF8
    Remove-OlderCompletedUpdates
} catch { Write-Warning ('Could not finish update housekeeping: ' + $_.Exception.Message) }

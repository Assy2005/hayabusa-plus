param(
    # -Public で 0.0.0.0 にバインドし、LAN 公開 (危険度ランキング) モードで起動する。
    [switch]$Public
)

# Hayabusa GUI launcher.
#
# The server prefers port 8787 but falls back to a random one if it's
# taken (typically by a zombie server from a previous launch, especially
# an elevated one we can't kill). This launcher therefore:
#   1. Wipes any stale port file from a prior run.
#   2. Starts the server in the background.
#   3. Waits up to ~10 s for the server to write its actual port to
#      workspace/.port .
#   4. Opens the browser at THAT port (not a hardcoded 8787).
#   5. Stays in the foreground so Ctrl+C cleanly stops the server.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python 3.x required on PATH." }

$env:HAYABUSA_GUI_PORT = if ($env:HAYABUSA_GUI_PORT) { $env:HAYABUSA_GUI_PORT } else { '8787' }

if ($Public) {
    $env:HAYABUSA_GUI_HOST = '0.0.0.0'
    # ASCII only: Windows PowerShell 5.1 misreads non-ASCII in .ps1 (cp932) and
    # can break the line. The Python server prints a JP banner correctly anyway.
    Write-Host "==> PUBLIC (LAN) mode: binding 0.0.0.0. Use only on a trusted LAN." -ForegroundColor Yellow
    Write-Host ("    Allow inbound TCP port {0} in Windows Firewall." -f $env:HAYABUSA_GUI_PORT) -ForegroundColor Yellow
}

# --- Make sure the preferred port is free so we don't drift to a random one.
# The usual cause of "the port changes every launch" is a leftover server:
#   (a) a zombie Windows python still running gui/server.py, or
#   (b) a server left running INSIDE WSL, which WSL mirrors onto Windows
#       127.0.0.1:<port> via wslrelay.exe (localhost forwarding).
# We only stop OUR OWN server; anything else we just warn about.
$preferred = [int]$env:HAYABUSA_GUI_PORT
$holderPid = $null
try {
    $holderPid = (Get-NetTCPConnection -LocalPort $preferred -State Listen -ErrorAction Stop |
                  Select-Object -First 1).OwningProcess
} catch {}
if ($holderPid) {
    $holder = Get-Process -Id $holderPid -ErrorAction SilentlyContinue
    $ours = Get-CimInstance Win32_Process -Filter "ProcessId=$holderPid" -ErrorAction SilentlyContinue
    if ($ours -and $ours.CommandLine -like '*server.py*') {
        Write-Host ("Freeing port {0}: stopping a previous server (PID {1})." -f $preferred, $holderPid) -ForegroundColor Yellow
        Stop-Process -Id $holderPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
    elseif ($holder -and $holder.ProcessName -eq 'wslrelay') {
        Write-Host ("Port {0} is held by a leftover server inside WSL. Stopping it." -f $preferred) -ForegroundColor Yellow
        try { wsl.exe -e sh -c "pkill -f 'gui/server.py' 2>/dev/null; fuser -k $preferred/tcp 2>/dev/null; true" | Out-Null } catch {}
        Start-Sleep -Seconds 1
    }
    else {
        $hn = if ($holder) { $holder.ProcessName } else { 'another process' }
        Write-Host ("Note: port {0} is in use by {1} (PID {2}); a different port will be chosen." -f $preferred, $hn, $holderPid) -ForegroundColor Yellow
    }
}

$workspace = Join-Path $here 'workspace'
New-Item -ItemType Directory -Path $workspace -Force | Out-Null
$portFile = Join-Path $workspace '.port'
Remove-Item $portFile -ErrorAction SilentlyContinue

$serverScript = Join-Path $here 'gui\server.py'

# Launch the server. We keep its stdout/stderr live in this console so
# the user can see what's happening; the server uses flush=True for its
# startup banner so the messages appear immediately.
$proc = Start-Process -FilePath $py.Source -ArgumentList "`"$serverScript`"" `
        -NoNewWindow -PassThru

# Poll for the port file. The server writes it ~immediately after the
# socket is open, so a 10-second budget is generous.
$port = $null
for ($i = 0; $i -lt 50; $i++) {
    if (Test-Path $portFile) {
        try { $port = (Get-Content $portFile -Raw -ErrorAction Stop).Trim() } catch {}
        if ($port) { break }
    }
    if ($proc.HasExited) {
        Write-Host ""
        Write-Host "Server exited before reporting a port. Check the messages above." -ForegroundColor Red
        exit 1
    }
    Start-Sleep -Milliseconds 200
}

if (-not $port) {
    Write-Host ""
    Write-Host "Server did not write a port file within 10s. Continuing without opening the browser." -ForegroundColor Yellow
    Write-Host "Look for a 'Listen : http://127.0.0.1:<port>/' line in the output above." -ForegroundColor Yellow
} else {
    $url = "http://127.0.0.1:$port"
    Start-Process $url | Out-Null
}

# Block until the server exits so Ctrl+C in this terminal propagates.
try {
    $proc.WaitForExit()
} finally {
    Remove-Item $portFile -ErrorAction SilentlyContinue
}

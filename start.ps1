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

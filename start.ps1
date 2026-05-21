# Hayabusa GUI launcher.
# Starts the Python web server bound to 127.0.0.1:8787 and opens the browser.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python 3.x required on PATH." }

$env:HAYABUSA_GUI_PORT = if ($env:HAYABUSA_GUI_PORT) { $env:HAYABUSA_GUI_PORT } else { '8787' }
Start-Process "http://127.0.0.1:$($env:HAYABUSA_GUI_PORT)" | Out-Null
& $py.Source (Join-Path $here 'gui\server.py')

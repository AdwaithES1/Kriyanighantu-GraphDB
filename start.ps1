# One-step start: launches Neo4j if needed, then the web app, then opens the browser.
$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"

function Test-Port([int]$port) {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $port); return $true } catch { return $false } finally { $client.Close() }
}

if (-not (Test-Path $python)) { throw "Python environment not found. Follow 'First-time setup' in README.md." }

if (Test-Port 7688) {
    Write-Host "Neo4j is already running."
} else {
    Write-Host "Starting Neo4j in a new window..."
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $project "start_neo4j.ps1")
    $deadline = (Get-Date).AddSeconds(120)
    while (-not (Test-Port 7688)) {
        if ((Get-Date) -gt $deadline) { throw "Neo4j did not start within 2 minutes. Check its window for errors." }
        Start-Sleep -Seconds 2
    }
    Write-Host "Neo4j is ready."
}

$ErrorActionPreference = "Continue"  # Flask writes normal notices to stderr
& $python (Join-Path $project "webapp\app.py") --open

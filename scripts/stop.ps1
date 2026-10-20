$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot '.runtime\server.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'Echo Ego is not running.'; exit 0 }
$serverProcessId = [int](Get-Content -LiteralPath $pidPath)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverProcessId"
$runPath = Join-Path $projectRoot 'run.py'
if ($process) {
    if ($process.CommandLine -notlike ('*' + $runPath + '*')) { throw 'PID belongs to another process. Refusing to stop it.' }
    # Let the controller close its owned inference workers first.
    $configPath = Join-Path $projectRoot 'config.local.json'
    if (-not (Test-Path -LiteralPath $configPath)) { $configPath = Join-Path $projectRoot 'config.example.json' }
    $port = (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).port
    try { Invoke-RestMethod ('http://127.0.0.1:' + $port + '/api/shutdown') -Method Post -TimeoutSec 15 | Out-Null } catch {}
    Start-Sleep -Seconds 1
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverProcessId"
}
if ($process) {
    # The uv Python trampoline can leave a child interpreter serving HTTP.
    $consoleHostPath = Join-Path $env:SystemRoot 'System32\conhost.exe'
    $childProcesses = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$serverProcessId" | Where-Object { $_.ExecutablePath -ine $consoleHostPath })
    foreach ($childProcess in $childProcesses) {
        if ($childProcess.CommandLine -notlike ('*' + $runPath + '*')) { throw 'Unexpected child process. Refusing to stop it.' }
    }
    foreach ($childProcess in $childProcesses) { Stop-Process -Id $childProcess.ProcessId }
    Stop-Process -Id $serverProcessId
}
Remove-Item -LiteralPath $pidPath
Write-Host 'Echo Ego stopped.'

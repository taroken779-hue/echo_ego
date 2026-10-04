$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot '.runtime\server.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Host 'Echo Ego is not running.'; exit 0 }
$serverProcessId = [int](Get-Content -LiteralPath $pidPath)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverProcessId"
$runPath = Join-Path $projectRoot 'run.py'
if ($process) {
    if ($process.CommandLine -notlike ('*' + $runPath + '*')) { throw 'PID belongs to another process. Refusing to stop it.' }
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

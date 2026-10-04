$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$configPath = Join-Path $projectRoot 'config.local.json'
$config = Get-Content -LiteralPath $(if (Test-Path -LiteralPath $configPath) { $configPath } else { Join-Path $projectRoot 'config.example.json' }) -Raw | ConvertFrom-Json
$port = [int]$config.port
$appUrl = 'http://127.0.0.1:' + $port
try {
    $status = Invoke-RestMethod ($appUrl + '/api/status') -TimeoutSec 2
    if ($status.app -eq 'echo-ego-prototype') { Start-Process $appUrl; exit 0 }
    throw 'Port is used by another application.'
} catch {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw 'Port is already in use. Stop that application first.' }
}
$pythonPath = $config.python_path
if (-not [IO.Path]::IsPathRooted($pythonPath)) { $pythonPath = Join-Path $projectRoot $pythonPath }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment was not found. Run setup.bat, or set python_path in config.local.json.' }
$runPath = Join-Path $projectRoot 'run.py'
$process = Start-Process -FilePath $pythonPath -ArgumentList ('"' + $runPath + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'server.log') -RedirectStandardError (Join-Path $runtimeDir 'server-error.log')
$process.Id | Set-Content (Join-Path $runtimeDir 'server.pid')
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $status = Invoke-RestMethod ($appUrl + '/api/status') -TimeoutSec 2
        if ($status.app -eq 'echo-ego-prototype') {
            Write-Host ('Echo Ego: ' + $appUrl + ' (model warms up in the background)')
            Start-Process $appUrl
            exit 0
        }
    } catch {}
    if ($process.HasExited) { Get-Content (Join-Path $runtimeDir 'server-error.log') -Tail 20; throw 'Echo Ego failed to start.' }
}
throw 'Startup timed out. Check .runtime/server-error.log.'

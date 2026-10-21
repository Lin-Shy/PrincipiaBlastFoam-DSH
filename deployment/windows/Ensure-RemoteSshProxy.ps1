[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')][string]$HostAlias,
    [Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int]$Port
)
$ErrorActionPreference = 'Stop'
$description = @(& ssh -G $HostAlias 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve SSH proxy Host.' }
$userLine = $description | Where-Object { $_ -match '^user ' } | Select-Object -First 1
if (-not $userLine -or $userLine -eq 'user root') { throw 'SSH proxy must also use a non-root user.' }
if ($description | Where-Object { $_ -match '^(remoteforward|localforward|dynamicforward) ' }) {
    throw 'Use a dedicated SSH Host without inherited forwarding rules.'
}
$probe = "curl -fsSI --connect-timeout 3 --max-time 8 --proxy http://127.0.0.1:$Port https://update.code.visualstudio.com/ >/dev/null 2>&1"
& ssh -o BatchMode=yes -o ConnectTimeout=8 -o ClearAllForwardings=yes $HostAlias $probe
if ($LASTEXITCODE -eq 0) { return }
if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    throw "Local proxy is not listening on port $Port."
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$stateDirectory = Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
$sshExecutable = (Get-Command ssh -ErrorAction Stop).Source
$proxyProcess = Start-Process -FilePath $sshExecutable -ArgumentList @(
    '-N','-T','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
    '-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3',
    '-R',"127.0.0.1:${Port}:127.0.0.1:${Port}",$HostAlias
) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $stateDirectory "ssh-proxy-$Port.out.log") -RedirectStandardError (Join-Path $stateDirectory "ssh-proxy-$Port.err.log")
Set-Content -LiteralPath (Join-Path $stateDirectory "ssh-proxy-$Port.pid") -Value $proxyProcess.Id -Encoding ASCII
for ($attempt = 0; $attempt -lt 5; $attempt++) {
    Start-Sleep -Milliseconds 300
    if ($proxyProcess.HasExited) { throw 'SSH proxy forwarding exited; inspect .local proxy logs.' }
    & ssh -o BatchMode=yes -o ConnectTimeout=8 -o ClearAllForwardings=yes $HostAlias $probe
    if ($LASTEXITCODE -eq 0) { return }
}
if (-not $proxyProcess.HasExited) { Stop-Process -Id $proxyProcess.Id }
throw 'SSH proxy forwarding did not become ready.'

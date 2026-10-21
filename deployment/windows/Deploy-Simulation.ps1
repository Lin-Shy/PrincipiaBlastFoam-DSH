[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RemoteDirectory,
    [string]$SshHost='yan_yun_agent',
    [string]$RemotePython='python3'
)
$ErrorActionPreference='Stop'
$sshDescription = @(& ssh -G $SshHost 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve SSH Host.' }
$sshUser = ($sshDescription | Where-Object { $_ -match '^user ' } | Select-Object -First 1) -replace '^user ', ''
if (-not $sshUser -or $sshUser -eq 'root') { throw 'Simulation SSH must use a non-root user.' }
# Restrict command interpolation to ordinary absolute POSIX paths/identifiers.
if ($RemoteDirectory -notmatch '^/[A-Za-z0-9_./-]+$' -or $RemoteDirectory -eq '/' -or $RemoteDirectory.Split('/') -contains '..') {
    throw 'RemoteDirectory must be a non-root absolute Linux path without shell metacharacters.'
}
if ($RemotePython -notmatch '^[A-Za-z0-9_./-]+$') { throw 'RemotePython must be a Python command/path.' }
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python=Join-Path $projectRoot '.venv/Scripts/python.exe'
& $python (Join-Path $projectRoot 'deployment/remote/build_package.py')
if ($LASTEXITCODE -ne 0) { throw 'Failed to build service archive.' }
& ssh -o BatchMode=yes -o ClearAllForwardings=yes $SshHost "mkdir -p -- '$RemoteDirectory'"
if ($LASTEXITCODE -ne 0) { throw 'SSH authentication or remote directory creation failed.' }
& scp -o BatchMode=yes -o ClearAllForwardings=yes (Join-Path $projectRoot '.local/simulation-service.tar.gz') "$($SshHost):$RemoteDirectory/service.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'Service upload failed.' }
& ssh -o BatchMode=yes -o ClearAllForwardings=yes $SshHost "cd '$RemoteDirectory' && tar -xzf service.tar.gz && bash install.sh '$RemoteDirectory' '$RemotePython'"
if ($LASTEXITCODE -ne 0) { throw 'Remote installation failed.' }
Write-Host 'Service files and dependencies installed. Configure simulation.env and the supplied systemd unit with actual solver environment paths and a non-root execution user.'

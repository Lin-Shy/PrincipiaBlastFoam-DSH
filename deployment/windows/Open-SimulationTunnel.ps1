[CmdletBinding()]
param([string]$SshHost='yan_yun_agent', [int]$LocalPort=8000, [int]$RemotePort=8000)
$ErrorActionPreference='Stop'
$sshDescription = @(& ssh -G $SshHost 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve SSH Host.' }
$sshUser = ($sshDescription | Where-Object { $_ -match '^user ' } | Select-Object -First 1) -replace '^user ', ''
if (-not $sshUser -or $sshUser -eq 'root') { throw 'Simulation SSH must use a non-root user.' }
# Proxy forwarding, if needed, is managed separately by Ensure-RemoteSshProxy.ps1.
# Do not set ClearAllForwardings here: it would also clear the requested -L.
& ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L "127.0.0.1:$($LocalPort):127.0.0.1:$RemotePort" $SshHost
if ($LASTEXITCODE -ne 0) { throw "SSH tunnel failed ($LASTEXITCODE)" }

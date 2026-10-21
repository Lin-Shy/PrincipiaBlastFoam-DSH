[CmdletBinding()]
param(
    [ValidateSet(3,4)][int]$Chapter = 3,
    [ValidateSet('web','headless')][string]$Profile = 'web',
    [switch]$Remote,
    [switch]$Ssh,
    [switch]$DumpConfig,
    [string]$CaseRoot,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$TaskArguments
)
$ErrorActionPreference = 'Stop'
if ($Ssh -and $Remote) { throw 'Choose -Ssh (SSH workspace) or -Remote (simulation MCP), not both.' }
if ($Ssh -and $Profile -ne 'web') { throw '-Ssh currently uses the dedicated web-ssh profile; select -Profile web.' }
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$baseRoot = Split-Path (Split-Path $projectRoot -Parent) -Parent
$localConfig = Join-Path $projectRoot '.local/windows.ps1'
if (Test-Path -LiteralPath $localConfig) { . $localConfig }
if (-not $env:DSH_CHECKOUT) { $env:DSH_CHECKOUT = Join-Path $baseRoot 'deepseek-harness' }
$env:DSH_HOME = Join-Path $baseRoot "dsh-home/chapter$Chapter"
$env:PRINCIPIA_PROJECT_ROOT = $projectRoot
$env:PRINCIPIA_PYTHON = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:BLASTFOAM_TUTORIALS = Join-Path (Split-Path $projectRoot -Parent) 'graduation-datasets/raw-corpus/blastfoam/blastFoam_tutorials'
$env:ENABLE_EXECUTION = 'false' # Local Windows solver is unavailable.
$env:REQUIRE_EXECUTION = if ($Remote) { 'true' } else { 'false' }
$env:DSH_TELEMETRY_MODE = 'DISABLED'
$env:PYTHONUTF8 = '1'
$env:PATH = (Join-Path $baseRoot 'dsh-tools') + ';' + $env:PATH
$entry = Join-Path $env:DSH_CHECKOUT 'apps/cli/lib/bin.js'
if (-not (Test-Path -LiteralPath $entry)) { throw 'Build the pinned DeepSeek Harness installation first.' }
if (-not (Test-Path -LiteralPath $env:PRINCIPIA_PYTHON)) { throw 'Install the project Python .venv first.' }
$effectiveProfile = if ($Ssh) { 'web-ssh' } else { $Profile }
$arguments = @('--profile', $effectiveProfile)
if ($Ssh) {
    if (-not $env:PRINCIPIA_SSH_HOST) { throw 'Set PRINCIPIA_SSH_HOST in .local/windows.ps1.' }
    $env:DSH_REMOTE_SSH_TARGET = $env:PRINCIPIA_SSH_HOST
    $sshDescription = @(& ssh -G $env:PRINCIPIA_SSH_HOST 2>$null)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the configured OpenSSH Host.' }
    $sshUser = ($sshDescription | Where-Object { $_ -match '^user ' } | Select-Object -First 1) -replace '^user ', ''
    if (-not $sshUser -or $sshUser -eq 'root') { throw 'SSH simulation must use an explicitly configured non-root user.' }
    $chapterWorkspace = [Environment]::GetEnvironmentVariable("PRINCIPIA_SSH_CHAPTER${Chapter}_WORKSPACE")
    if ($chapterWorkspace) { $env:DSH_REMOTE_SSH_WORKSPACE = $chapterWorkspace }
    $manifestPath = Join-Path $env:DSH_HOME "profiles/$effectiveProfile/package.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Install the dedicated web-ssh profile first; see deployment/dsh/README.md.' }
    $manifestContent = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if (-not $manifestContent.dependencies.'dsh-remote-ssh') { throw 'The web-ssh profile must include dsh-remote-ssh.' }
    $arguments += @('--patch', (Join-Path $projectRoot 'deployment/dsh/remote-ssh.patch.example.yml'))
}
if ($Chapter -eq 4) {
    # A separate working directory prevents discovery of Chapter 3 project skills.
    $workspace = Join-Path $env:DSH_HOME 'workspace'
    New-Item -ItemType Directory -Force -Path $workspace | Out-Null
    $arguments += @('--patch', (Join-Path $projectRoot 'deployment/dsh/single-agent.patch.example.yml'))
    $manifest = Join-Path $env:DSH_HOME "profiles/$effectiveProfile/package.json"
    if (Test-Path -LiteralPath $manifest) {
        if ((Get-Content -Raw -LiteralPath $manifest) -match 'principia-blastfoam-dsh-bundle') {
            throw 'Chapter 4 profile contains the Chapter 3 bundle; use a clean dedicated profile.'
        }
    }
} else { $workspace = $projectRoot }
$env:PRINCIPIA_CASE_ROOT = if ($CaseRoot) { $CaseRoot } else { Join-Path $workspace 'outputs' }
if ($Remote) {
    if (-not $env:PRINCIPIA_REMOTE_SIMULATION_ROOT) { throw 'Set PRINCIPIA_REMOTE_SIMULATION_ROOT in .local/windows.ps1.' }
    $arguments += @('--patch', (Join-Path $projectRoot 'deployment/dsh/simulation.patch.example.yml'))
}
if ($Ssh -and -not $DumpConfig -and $env:PRINCIPIA_SSH_PROXY_PORT) {
    & (Join-Path $PSScriptRoot 'Ensure-RemoteSshProxy.ps1') -HostAlias $env:PRINCIPIA_SSH_HOST -Port ([int]$env:PRINCIPIA_SSH_PROXY_PORT)
}
if ($DumpConfig) { $arguments += '--dump-config' }
$arguments += $TaskArguments
Push-Location $workspace
try {
    # Windows PowerShell treats redirected native stderr as ErrorRecord objects.
    # MCP diagnostics on stderr must not abort an otherwise successful DSH boot.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & node $entry @arguments
        $dshExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    if ($dshExitCode -ne 0) { throw "DSH exited with code $dshExitCode" }
}
finally { Pop-Location }

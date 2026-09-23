<#
.SYNOPSIS
    Installs or updates the Werkbank engine on Windows (DESIGN.md section 6.3).

.DESCRIPTION
    1. Installs uv, FFmpeg, Deno and Node.js LTS with winget, skipping any that are already present.
       Each winget package ID is verified with `winget show` before it is used.
    2. Sets up the engine's Python environment (uv installs Python 3.12 if needed).
    3. Installs the UI's packages and builds the UI that the engine serves.
    4. Creates a "Werkbank" shortcut on the desktop and starts Werkbank.

    Safe to re-run: after `git pull`, run it again to update.

    Run from the repository folder:
        powershell -ExecutionPolicy Bypass -File scripts\install.ps1

.PARAMETER NoShortcut
    Do not create the desktop shortcut.

.PARAMETER NoStart
    Do not start Werkbank at the end.
#>
[CmdletBinding()]
param(
    [switch]$NoShortcut,
    [switch]$NoStart
)

# This file must stay ASCII-only: Windows PowerShell 5.1 reads BOM-less files in the ANSI code page.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$MinNodeMajor = 22
# winget returns this when the package is already installed and no upgrade applies.
$WingetNoUpgradeApplicable = -1978335189  # 0x8A15002B

$Packages = @(
    @{ Id = 'astral-sh.uv';      Command = 'uv';     Name = 'uv (Python manager)' },
    @{ Id = 'Gyan.FFmpeg';       Command = 'ffmpeg'; Name = 'FFmpeg' },
    @{ Id = 'DenoLand.Deno';     Command = 'deno';   Name = 'Deno' },
    @{ Id = 'OpenJS.NodeJS.LTS'; Command = 'node';   Name = 'Node.js LTS' }
)

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native([string]$What, [scriptblock]$Command, [int[]]$OkCodes = @(0)) {
    # Windows PowerShell 5.1 turns a native program's stderr into errors when output is captured
    # (uv, npm and winget print progress there), so rely on the exit code instead.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($OkCodes -notcontains $LASTEXITCODE) {
        throw ("$What failed (exit code $LASTEXITCODE, " + ('0x{0:X8}' -f $LASTEXITCODE) + ').')
    }
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Merge-SessionPath {
    # Installers change the stored PATH, not this session's. Add the stored entries and the folder
    # where winget links portable packages (FFmpeg, Deno, uv), keeping this session's own entries.
    $parts = @($env:Path -split ';') +
        @([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') +
        @([Environment]::GetEnvironmentVariable('Path', 'User') -split ';') +
        @((Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'), (Join-Path $env:USERPROFILE '.local\bin'))
    $seen = @{}
    $result = New-Object System.Collections.Generic.List[string]
    foreach ($part in $parts) {
        if ($part -and -not $seen.ContainsKey($part.ToLowerInvariant())) {
            $seen[$part.ToLowerInvariant()] = $true
            $result.Add($part)
        }
    }
    $env:Path = $result -join ';'
}

function Get-NodeMajor {
    $script:nodeVersionText = ''
    Invoke-Native 'node --version' { $script:nodeVersionText = (& node --version) }
    $version = [string]$script:nodeVersionText
    if ($version -match '^v(\d+)\.') { return [int]$Matches[1] }
    return 0
}

function Install-WingetPackage($Package) {
    if (-not (Test-Command 'winget')) {
        throw ("winget is not available. Install 'App Installer' from the Microsoft Store, " +
               "or install $($Package.Name) yourself, then run this script again.")
    }
    Write-Host "Checking winget package $($Package.Id) ..."
    Invoke-Native "winget show $($Package.Id) (is the package ID still valid?)" {
        & winget show --id $Package.Id --exact --accept-source-agreements --disable-interactivity | Out-Null
    }
    Write-Host "Installing $($Package.Name) ($($Package.Id)) ..."
    Invoke-Native "winget install $($Package.Id)" -OkCodes @(0, $WingetNoUpgradeApplicable) {
        & winget install --id $Package.Id --exact --silent --accept-package-agreements `
            --accept-source-agreements --disable-interactivity
    }
}

Write-Host 'Werkbank installer' -ForegroundColor Green
Write-Host "Repository: $RepoRoot"
if (-not (Test-Path (Join-Path $RepoRoot 'engine\pyproject.toml'))) {
    throw 'Run this script from a copy of the Werkbank repository: scripts\install.ps1'
}

Write-Step 'Checking programs (uv, FFmpeg, Deno, Node.js)'
Merge-SessionPath
foreach ($package in $Packages) {
    if (Test-Command $package.Command) {
        Write-Host "$($package.Name): already installed"
        continue
    }
    Install-WingetPackage $package
    Merge-SessionPath
}

foreach ($package in $Packages) {
    if (-not (Test-Command $package.Command)) {
        throw ("$($package.Name) was installed but '$($package.Command)' is still not found. " +
               'Close this window, open a new PowerShell window and run the installer again.')
    }
}

$nodeMajor = Get-NodeMajor
if ($nodeMajor -lt $MinNodeMajor) {
    throw ("Node.js $MinNodeMajor or newer is needed (found major version $nodeMajor). " +
           'Update it, for example: winget upgrade --id OpenJS.NodeJS.LTS -e')
}

Invoke-Native 'uv --version' { & uv --version }
Invoke-Native 'ffmpeg -version' { $lines = @(& ffmpeg -hide_banner -version); $lines[0] }
Invoke-Native 'deno --version' { $lines = @(& deno --version); $lines[0] }
Write-Host "node $nodeMajor"

Push-Location $RepoRoot
try {
    Write-Step 'Setting up the engine (Python environment)'
    Invoke-Native 'uv sync' { & uv sync --project engine --frozen --no-dev }

    Write-Step 'Installing UI packages (npm ci)'
    Invoke-Native 'npm ci' { & npm ci --no-audit --no-fund }

    Write-Step 'Building the user interface'
    Invoke-Native 'UI build' { & npm run build -w apps/web }
}
finally {
    Pop-Location
}

$startScript = Join-Path $RepoRoot 'scripts\start.cmd'
if (-not $NoShortcut) {
    Write-Step 'Creating the desktop shortcut'
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $desktop 'Werkbank.lnk'))
    $shortcut.TargetPath = $startScript
    $shortcut.WorkingDirectory = $RepoRoot
    $shortcut.Description = 'Start the Werkbank engine and open it in the browser'
    $shortcut.Save()
    Write-Host "Shortcut: $(Join-Path $desktop 'Werkbank.lnk')"
}

Write-Step 'Done'
Write-Host 'Start Werkbank with the desktop shortcut, or run scripts\start.cmd.'
Write-Host 'It opens http://127.0.0.1:8765 in your browser. Close the engine window to stop it.'
Write-Host 'To update later: git pull, then run this installer again.'

if (-not $NoStart) {
    Start-Process -FilePath $startScript -WorkingDirectory $RepoRoot
}

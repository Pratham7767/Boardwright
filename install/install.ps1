<#
Boardwright installer for Windows.

From a clone of the repository:
    powershell -ExecutionPolicy Bypass -File install\install.ps1
Straight from GitHub (nothing to clone):
    irm https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.ps1 | iex

It asks before every change. Add -Yes to accept every question (only with the
file form: powershell -ExecutionPolicy Bypass -File install\install.ps1 -Yes).
-NoOpen skips opening Explorer at the add-on zip.
It never asks for, reads or stores a password, API key or token: sign-in is
Claude Code's own browser flow.
#>
param([switch]$Yes, [switch]$NoOpen)

$ErrorActionPreference = 'Continue'
$Repo = 'Pratham7767/Boardwright'
$AddonUrl = "https://github.com/$Repo/releases/latest/download/boardwright-kicad.zip"
$Here = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { $null }
$Local = $Here -and (Test-Path (Join-Path $Here '.claude-plugin\marketplace.json'))
$Todo = New-Object System.Collections.Generic.List[string]

function Say($m) { Write-Host $m }
function Step($n, $m) { Write-Host ''; Write-Host "$n. $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "   [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "   [!!] $m" -ForegroundColor Yellow; $Todo.Add($m) }
function Ask($q) {
    if ($Yes) { return $true }
    $a = Read-Host "   $q [y/N]"
    return ($a -match '^(y|yes)$')
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                (Join-Path $HOME '.local\bin')
}
function Has($exe) { [bool](Get-Command $exe -ErrorAction SilentlyContinue) }
function Winget($id, $what) {
    if (-not (Has 'winget')) { Warn "$what is missing and winget is not available; install it by hand"; return }
    if (Ask "Install $what with winget ($id)?") {
        winget install --id $id -e --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }
}
function Find-Python {
    foreach ($p in @('python', 'py')) {
        $cmd = Get-Command $p -ErrorAction SilentlyContinue
        if (-not $cmd -or $cmd.Source -like '*WindowsApps*') { continue }   # the Store stub
        $v = & $p -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]'3.10') { return $p }
    }
    return $null
}
function Find-KicadCli {
    if ($env:KICAD_CLI -and (Test-Path $env:KICAD_CLI)) { return $env:KICAD_CLI }
    if (Has 'kicad-cli') { return (Get-Command kicad-cli).Source }
    # Where Windows says KiCad is installed (any drive, any folder)
    $keys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    $dirs = @(Get-ItemProperty $keys -ErrorAction SilentlyContinue |
              Where-Object { $_.DisplayName -like 'KiCad*' -and $_.InstallLocation } |
              ForEach-Object { $_.InstallLocation })
    $dirs += @("$env:ProgramFiles\KiCad\*") + @(Get-PSDrive -PSProvider FileSystem | ForEach-Object {
               "$($_.Root)KiCad", "$($_.Root)KiCad\*" })
    foreach ($d in $dirs) {
        $c = Get-ChildItem (Join-Path $d 'bin\kicad-cli.exe') -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
        if ($c) { return $c.FullName }
    }
    return $null
}

Say 'Boardwright installer (Windows)'
if ($Local) { Say "Using this clone: $Here" } else { Say "Using GitHub: $Repo" }
Refresh-Path
if (-not $Yes) {
    Say ''
    Say 'It will install whatever is missing, from official sources only: KiCad (winget), Python, Git,'
    Say 'Claude Code, the boardwright plugin and its helper tools; turn on KiCad''s API server setting;'
    Say 'prepare the KiCad add-on; and start Claude Code''s own sign-in in your browser.'
    $a = Read-Host 'Set up everything? [Y/n]  (n = ask me before each step)'
    if ($a -notmatch '^(n|no)$') { $Yes = $true }
}

Step 1 'KiCad 9 or 10'
$cli = Find-KicadCli
if (-not $cli) { Winget 'KiCad.KiCad' 'KiCad'; $cli = Find-KicadCli }
if ($cli) { Ok "kicad-cli: $cli" } else { Warn 'KiCad: install KiCad 9 or 10 from https://www.kicad.org/download/' }

Step 2 'Python 3.10 or newer (runs the gate scripts)'
$py = Find-Python
if (-not $py) { Winget 'Python.Python.3.12' 'Python 3.12'; $py = Find-Python }
if ($py) { Ok "python: $((Get-Command $py).Source)" } else { Warn 'Python: install 3.10+ from https://www.python.org and tick "Add python.exe to PATH"' }

Step 3 'Git (Claude Code on Windows needs it)'
if (-not (Has 'git')) { Winget 'Git.Git' 'Git' }
if (Has 'git') { Ok 'git found' } else { Warn 'Git: install from https://git-scm.com' }

Step 4 'Claude Code'
if (-not (Has 'claude')) {
    Say '   Official installer: irm https://claude.ai/install.ps1 | iex   (https://code.claude.com/docs/en/setup)'
    if (Ask 'Install Claude Code now with the official installer?') {
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        Refresh-Path
    }
}
if (Has 'claude') { Ok "claude: $(& claude --version)" } else { Warn 'Claude Code: install it from https://code.claude.com/docs/en/setup' }

Step 5 'The boardwright Claude Code plugin'
if (Has 'claude') {
    $src = if ($Local) { $Here } else { $Repo }
    $known = (& claude plugin marketplace list --json 2>$null | Out-String) -match '"name":\s*"boardwright"'
    if ($known) { & claude plugin marketplace update boardwright | Out-Null }
    elseif (Ask "Add the boardwright marketplace ($src) to Claude Code?") { & claude plugin marketplace add $src }
    $have = (& claude plugin list --json 2>$null | Out-String) -match '"id":\s*"boardwright@boardwright"'
    if ($have) { & claude plugin update boardwright@boardwright | Out-Null; Ok 'plugin installed (updated if a newer version exists)' }
    elseif (Ask 'Install the boardwright plugin for your user?') {
        & claude plugin install boardwright@boardwright
        if ($LASTEXITCODE -eq 0) { Ok 'plugin installed' } else { Warn 'plugin install failed; see the message above' }
    } else { Warn 'plugin: claude plugin install boardwright@boardwright' }
}

Step 6 'Helper tools (uv, kicad-buddy, schematic tools, KiCad API setting)'
$setup = $null
if ($Local) { $setup = Join-Path $Here 'plugin\scripts\setup.py' }
elseif (Has 'claude') {
    $list = & claude plugin list --json 2>$null | Out-String | ConvertFrom-Json
    $p = $list | Where-Object { $_.id -eq 'boardwright@boardwright' } | Select-Object -First 1
    if ($p) { $setup = Join-Path $p.installPath 'scripts\setup.py' }
}
if ($py -and $setup -and (Test-Path $setup)) {
    $args2 = @($setup); if ($Yes) { $args2 += '--yes' }
    & $py @args2
    if ($LASTEXITCODE -ne 0) { Warn 'helper setup left items open; its summary is above' }
} else { Warn 'helper setup skipped (needs Python and the plugin); later run: python <plugin>\scripts\setup.py' }

Step 7 'The KiCad add-on (chat button in the PCB Editor)'
$zip = $null
if ($Local -and $py) {
    & $py (Join-Path $Here 'kicad-addon\build.py') | Out-Null
    $zip = Join-Path $Here 'kicad-addon\dist\boardwright-kicad.zip'
} elseif (Ask "Download the add-on zip from $AddonUrl ?") {
    $zip = Join-Path $env:TEMP 'boardwright-kicad.zip'
    try { Invoke-WebRequest $AddonUrl -OutFile $zip -UseBasicParsing } catch { $zip = $null; Warn "download failed: $_" }
}
if ($zip -and (Test-Path $zip)) {
    Ok "add-on package: $zip"
    Say '   KiCad installs add-ons itself. In KiCad''s main window:'
    Say '   Plugin and Content Manager > Install from File... > pick the file above > Close, then restart KiCad.'
    if (-not $NoOpen) { Start-Process explorer.exe "/select,`"$zip`"" }
    $Todo.Add("KiCad add-on: Plugin and Content Manager > Install from File... > $zip, then restart KiCad")
} else { Warn 'KiCad add-on: get boardwright-kicad.zip from the Releases page and use Install from File...' }

Step 8 'Sign in to Claude Code'
if (Has 'claude') {
    $st = & claude auth status --json 2>$null | Out-String
    if ($st -match '"loggedIn":\s*true') { Ok 'signed in' }
    elseif (Ask 'Start Claude Code''s own sign-in now (your browser opens)?') { & claude auth login }
    else { Warn 'sign in later with: claude auth login' }
}

Write-Host ''
if ($Todo.Count -eq 0) { Write-Host 'Done. Everything is in place.' -ForegroundColor Green }
else {
    Write-Host 'Done, with these left for you:' -ForegroundColor Yellow
    $Todo | ForEach-Object { Write-Host "  - $_" }
}
Say 'Next: make an empty folder for a board, open it in Claude Code, and run /boardwright:pcb-new'

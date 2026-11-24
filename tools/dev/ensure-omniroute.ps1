# Developer setup: make sure OmniRoute (an AI gateway, https://github.com/cheaper-inference/OmniRoute, MIT) is
# installed and running on this computer, so Claude Code can keep working on Boardwright through other AI
# providers when the Claude plan's limit is reached. For people developing Boardwright; the product itself does
# not need it.
#
#   powershell -ExecutionPolicy Bypass -File tools\dev\ensure-omniroute.ps1          install if missing, start
#   powershell -ExecutionPolicy Bypass -File tools\dev\ensure-omniroute.ps1 -Check   say what is there, change nothing
#
# Everything goes into %LOCALAPPDATA%\Boardwright\dev (or BOARDWRIGHT_DEV_DIR): a private Node.js 24 (OmniRoute
# needs Node 22.22+ or 24+; the system Node is left alone) and OmniRoute, both pinned and checked by checksum.
# This script never reads, writes or prints an OmniRoute key: you create keys in OmniRoute's own dashboard.
param([switch]$Check, [switch]$Quiet)
$ErrorActionPreference = "Stop"
$NodeVer = "24.22.3"
$NodeSha = "e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f"
$OmniVer = "3.8.54"
$Port = 20128
$Root = if ($env:BOARDWRIGHT_DEV_DIR) { $env:BOARDWRIGHT_DEV_DIR } else { Join-Path $env:LOCALAPPDATA "Boardwright\dev" }
$NodeDir = Join-Path $Root "node-v$NodeVer-win-x64"
$Node = Join-Path $NodeDir "node.exe"
$Npm = Join-Path $NodeDir "npm.cmd"
$Prefix = Join-Path $Root "omniroute"
$Omni = Join-Path $Prefix "omniroute.cmd"
function Say($m) { if (-not $Quiet) { Write-Host $m } }

function Test-Running {
  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $Port); $c.Close(); return $true } catch { return $false }
}

if ($Check) {
  Say ("node 24      " + $(if (Test-Path $Node) { "ok ($NodeDir)" } else { "missing" }))
  Say ("omniroute    " + $(if (Test-Path $Omni) { "ok ($Omni)" } else { "missing" }))
  Say ("running      " + $(if (Test-Running) { "yes, http://localhost:$Port" } else { "no" }))
  exit 0
}

New-Item -ItemType Directory -Force $Root | Out-Null
if (-not (Test-Path $Node)) {
  Say "download  Node.js $NodeVer (private copy for OmniRoute)"
  $zip = Join-Path $Root "node.zip"
  Invoke-WebRequest -UseBasicParsing "https://nodejs.org/dist/v$NodeVer/node-v$NodeVer-win-x64.zip" -OutFile $zip
  if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $NodeSha) { Remove-Item $zip; throw "Node.js: checksum does not match; nothing installed." }
  Expand-Archive $zip -DestinationPath $Root -Force
  Remove-Item $zip
}
if (-not (Test-Path $Omni)) {
  Say "install   OmniRoute $OmniVer (npm, into $Prefix)"
  $env:PATH = "$NodeDir;$env:PATH"
  # npm 11 runs install scripts only for packages it is told to allow; OmniRoute's own needs these
  & $Npm install -g --prefix $Prefix "omniroute@$OmniVer" `
    --allow-scripts=omniroute,keytar,onnxruntime-node,@parcel/watcher,@swc/core,protobufjs,esbuild --no-fund --no-audit
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Omni)) { throw "installing OmniRoute failed (see npm's messages above)" }
}
if (-not (Test-Running)) {
  Say "start     OmniRoute on http://localhost:$Port"
  $log = Join-Path $Root "omniroute.log"
  $env:PATH = "$NodeDir;$env:PATH"
  Start-Process -WindowStyle Hidden -FilePath $Omni -RedirectStandardOutput $log -RedirectStandardError "$log.err"
}
Say "ready     OmniRoute: dashboard http://localhost:$Port (connect providers and create a key there)"
Say "          use it:   $Omni launch      (starts Claude Code through OmniRoute)"

# Boardwright routing engine: installs the tools the deterministic engine uses, into
# %LOCALAPPDATA%\Boardwright\engine (nothing in your projects, nothing system-wide).
#
#   powershell -ExecutionPolicy Bypass -File plugin\scripts\setup_engine.ps1   (the installer runs it for you)
#
# What it fetches (each pinned to one version and checked against its published SHA-256 before use):
#   - Freerouting 2.5.1 nightly of 2026-11-16, commit 12f085e (GPL-3, a separate program;
#     https://github.com/freerouting/freerouting): its official image on ghcr.io, only the layer that holds the
#     jar, checked against the layer's SHA-256 and the jar's own. It applies the board-edge and hole clearances
#     that 2.5.0 ignored (routing benchmark in docs/benchmark-engine.md).
#   - a Java 25 runtime for it (Eclipse Temurin, https://adoptium.net)
#   - KiCadRoutingTools 0.24.1 (MIT, https://github.com/drandyhaas/KiCadRoutingTools) and its prebuilt router
#   - the Python packages KiCadRoutingTools needs (numpy, scipy, shapely, Pillow, ortools) in its own environment
# Run it again at any time: what is already there and correct is kept.
$ErrorActionPreference = "Stop"
$Root = if ($env:BOARDWRIGHT_ENGINE_DIR) { $env:BOARDWRIGHT_ENGINE_DIR } else { Join-Path $env:LOCALAPPDATA "Boardwright\engine" }
New-Item -ItemType Directory -Force $Root | Out-Null

$Files = @(
  @{ Name = "jre"; Url = "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jre_x64_windows_hotspot_25.0.5_8.zip";
     Sha = "da78d54a2fcdbba1e92d5e3f07dd30236f96297891c4a21a781c3f38f5c0beae"; File = "jre.zip" },
  @{ Name = "krt"; Url = "https://github.com/drandyhaas/KiCadRoutingTools/releases/download/v0.24.1/KiCadRoutingTools-0.24.1.zip";
     Sha = "95fe2610a591b2b5702d41e8e85b89dc5318a48d75f528e2b866c3b3ced5fdb2"; File = "krt.zip" },
  @{ Name = "krt-router"; Url = "https://github.com/drandyhaas/KiCadRoutingTools/releases/download/v0.24.1/grid_router-windows-x86_64.pyd";
     Sha = "80309be6060187cf7ac357f13b16806472709e774447213ddffd8c66889526a6"; File = "grid_router.pyd" }
)

function Get-Checked($f) {
  $dst = Join-Path $Root $f.File
  if ((Test-Path $dst) -and ((Get-FileHash $dst -Algorithm SHA256).Hash.ToLower() -eq $f.Sha)) {
    Write-Host "ok        $($f.Name) (already here)"; return $dst
  }
  Write-Host "download  $($f.Name)"
  $tmp = "$dst.part"
  Invoke-WebRequest -UseBasicParsing $f.Url -OutFile $tmp
  $h = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
  if ($h -ne $f.Sha) { Remove-Item $tmp; throw "$($f.Name): checksum does not match (got $h). Nothing was installed from it." }
  Move-Item -Force $tmp $dst
  Write-Host "ok        $($f.Name) (checksum matches)"
  return $dst
}

$paths = @{}
foreach ($f in $Files) { $paths[$f.Name] = Get-Checked $f }

# Freerouting: the jar from the one layer of its official nightly image that holds it (anonymous registry access)
$frJar = Join-Path $Root "freerouting-2.5.1-nightly-12f085e.jar"
if ((Test-Path $frJar) -and ((Get-FileHash $frJar -Algorithm SHA256).Hash.ToLower() -eq "72a62bb5964f542fc946801e68fe450e8c3c80d98fb3e9b70bab2ecc80ae5dd4")) {
  Write-Host "ok        freerouting (already here)"
} else {
  Write-Host "download  freerouting"
  $tok = (Invoke-RestMethod -UseBasicParsing "https://ghcr.io/token?scope=repository:freerouting/freerouting:pull").token
  $layer = Join-Path $Root "freerouting-layer.tar.gz"
  Invoke-WebRequest -UseBasicParsing -Headers @{ Authorization = "Bearer $tok" } -OutFile $layer `
    "https://ghcr.io/v2/freerouting/freerouting/blobs/sha256:81c14637909e1e18f70d7808393ab1074e602df7583173f6aec761773e7b1c25"
  if ((Get-FileHash $layer -Algorithm SHA256).Hash.ToLower() -ne "81c14637909e1e18f70d7808393ab1074e602df7583173f6aec761773e7b1c25") {
    Remove-Item $layer; throw "freerouting: the image layer's checksum does not match. Nothing was installed from it." }
  $unz = Join-Path $Root "freerouting-unpack"
  Remove-Item -Recurse -Force $unz -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force $unz | Out-Null
  & tar -xzf $layer -C $unz app/freerouting-executable.jar
  $got = Join-Path $unz "app\freerouting-executable.jar"
  if (-not (Test-Path $got) -or (Get-FileHash $got -Algorithm SHA256).Hash.ToLower() -ne "72a62bb5964f542fc946801e68fe450e8c3c80d98fb3e9b70bab2ecc80ae5dd4") {
    Remove-Item -Recurse -Force $unz, $layer; throw "freerouting: the jar's checksum does not match. Nothing was installed." }
  Move-Item -Force $got $frJar
  Remove-Item -Recurse -Force $unz, $layer
  Write-Host "ok        freerouting (checksums match)"
}
$paths["freerouting"] = $frJar

# Java runtime for Freerouting
$jreDir = Join-Path $Root "jre"
if (-not (Get-ChildItem $jreDir -Recurse -Filter java.exe -ErrorAction SilentlyContinue)) {
  Expand-Archive $paths["jre"] -DestinationPath $jreDir -Force
}
$java = (Get-ChildItem $jreDir -Recurse -Filter java.exe | Select-Object -First 1).FullName
Write-Host "java      $java"

# KiCadRoutingTools: source, prebuilt router next to it, and a Python environment with its packages
$krtDir = Join-Path $Root "krt"
if (-not (Test-Path (Join-Path $krtDir "py_router\route.py"))) {
  $unz = Join-Path $Root "krt-unzip"
  Remove-Item -Recurse -Force $unz -ErrorAction SilentlyContinue
  Expand-Archive $paths["krt"] -DestinationPath $unz -Force
  # the package's root is the folder that holds py_router, py_placer, py_tools, awx ...
  $inner = Get-ChildItem $unz -Recurse -Directory -Filter py_router | Select-Object -First 1
  if (-not $inner) { throw "KiCadRoutingTools archive has no py_router folder" }
  Remove-Item -Recurse -Force $krtDir -ErrorAction SilentlyContinue
  Move-Item $inner.Parent.FullName $krtDir
  Remove-Item -Recurse -Force $unz -ErrorAction SilentlyContinue
}
$rr = Join-Path $krtDir "rust_router"
New-Item -ItemType Directory -Force $rr | Out-Null
Copy-Item -Force $paths["krt-router"] (Join-Path $rr "grid_router.pyd")
Copy-Item -Force $paths["krt-router"] (Join-Path $krtDir "grid_router.pyd")
# The release package has no rust_router/Cargo.toml; KiCadRoutingTools reads the router's version from it only to
# check that the prebuilt router matches, so write the pinned version there.
$cargo = Join-Path $rr "Cargo.toml"
if (-not (Test-Path $cargo)) { "[package]`nname = `"grid_router`"`nversion = `"0.24.1`"`n" | Set-Content -Encoding ascii $cargo }

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
$venv = Join-Path $Root "venv"
if (-not $uv) { throw "uv is needed (the main Boardwright installer sets it up). Run install\install.ps1 first." }
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { & $uv venv -q --python 3.13 $venv }
& $uv pip install -q --python (Join-Path $venv "Scripts\python.exe") "numpy>=1.22" "scipy>=1.7" "shapely>=2.0" "Pillow>=9.2" "ortools>=9.15"
if ($LASTEXITCODE -ne 0) { throw "installing KiCadRoutingTools' Python packages failed" }

# Record where everything is, for the engine
$cfg = @{ version = 1; java = $java; freerouting_jar = $paths["freerouting"]; krt = $krtDir;
          krt_python = (Join-Path $venv "Scripts\python.exe"); installed = (Get-Date -Format s) }
$cfg | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Root "engine.json")

# Smoke test
Write-Host "freerouting: $([math]::Round((Get-Item $paths['freerouting']).Length / 1MB)) MB jar in place"
& (Join-Path $venv "Scripts\python.exe") -c "import sys; sys.path.insert(0, r'$krtDir'); sys.path.insert(0, r'$rr'); import grid_router; print('KiCadRoutingTools router: ok')"
Write-Host ""
Write-Host "Done. The Boardwright engine tools are in $Root"

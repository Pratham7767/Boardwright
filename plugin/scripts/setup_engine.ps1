# Boardwright routing engine: installs the tools the deterministic engine uses, into
# %LOCALAPPDATA%\Boardwright\engine (nothing in your projects, nothing system-wide).
#
#   powershell -ExecutionPolicy Bypass -File plugin\scripts\setup_engine.ps1   (the installer runs it for you)
#
# What it fetches (each pinned to one version and checked against its published SHA-256 before use):
#   - Freerouting 2.6.0 (GPL-3, a separate program; https://github.com/freerouting/freerouting), its release jar
#     (routing benchmark in docs/benchmark-engine.md)
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
  @{ Name = "freerouting"; Url = "https://github.com/freerouting/freerouting/releases/download/v2.6.0/freerouting-2.6.0.jar";
     Sha = "a2929fe37767a71d119f52ac99a1615a9aa2b0538742fa514ddafd72a7785729"; File = "freerouting-2.6.0.jar" },
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

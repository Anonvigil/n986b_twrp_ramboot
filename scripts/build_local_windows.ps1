param(
  [Parameter(Mandatory = $true)][string]$ArtifactsDir,
  [string]$OutputZip = '',
  [string]$PythonExe = 'python'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$artifacts = (Resolve-Path -LiteralPath $ArtifactsDir).Path
if (-not $OutputZip) {
  $OutputZip = Join-Path $repo 'local\n986b-twrp-ramboot-local-complete.zip'
}
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
Push-Location $repo
try {
  if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonExe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed' }
  }
  & $venvPython -m pip install -r requirements-build.txt
  if ($LASTEXITCODE -ne 0) { throw 'Pinned launcher build dependencies failed to install' }
  & $venvPython -m unittest discover -s scripts -p 'test_*.py' -q
  if ($LASTEXITCODE -ne 0) { throw 'Offline launcher tests failed' }
  & $venvPython -m PyInstaller --onefile --console --clean --name N986B-TWRP-RAMBOOT scripts\ramboot.py
  if ($LASTEXITCODE -ne 0) { throw 'Launcher EXE build failed' }

  $dll = Join-Path $repo 'dist\libusb-1.0.dll'
  if (-not (Test-Path -LiteralPath $dll)) {
    $archive = Join-Path $repo 'dist\libusb-1.0.30.7z'
    if (-not (Test-Path -LiteralPath $archive)) {
      Invoke-WebRequest -Uri 'https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.7z' -OutFile $archive
    }
    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if ($archiveHash -ne '7FB1DFEC805B97983763D7D0AE244320DA12ADD1003D4249C96CC4D586398C79') {
      throw 'Pinned libusb archive SHA-256 mismatch'
    }
    $machine = (& $venvPython -c 'import platform; print(platform.machine().lower())').Trim()
    $bits = (& $venvPython -c 'import struct; print(struct.calcsize("P") * 8)').Trim()
    if ($machine -match 'arm64|aarch64') {
      $entry = 'VS2025/ARM64/dll/libusb-1.0.dll'
    } elseif ($bits -eq '32') {
      $entry = 'MinGW32/dll/libusb-1.0.dll'
    } elseif ($bits -eq '64') {
      $entry = 'MinGW64/dll/libusb-1.0.dll'
    } else {
      throw "Unsupported Python architecture: $machine / $bits bits"
    }
    $seven = Get-Command 7z.exe -ErrorAction SilentlyContinue
    $sevenPath = if ($seven) { $seven.Source } else { Join-Path ${env:ProgramFiles} '7-Zip\7z.exe' }
    if (-not (Test-Path -LiteralPath $sevenPath)) {
      throw '7-Zip is needed to extract the pinned libusb DLL. Install 7-Zip and retry.'
    }
    $extract = Join-Path $repo 'dist\libusb-extract'
    New-Item -ItemType Directory -Path $extract -Force | Out-Null
    & $sevenPath x $archive $entry "-o$extract" -y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'libusb extraction failed' }
    Copy-Item -LiteralPath (Join-Path $extract $entry) -Destination $dll
  }

  & (Join-Path $repo 'dist\N986B-TWRP-RAMBOOT.exe') probe-usb
  if ($LASTEXITCODE -ne 0) { throw 'Built launcher failed to load libusb' }
  & (Join-Path $repo 'dist\N986B-TWRP-RAMBOOT.exe') plan --artifacts $artifacts
  if ($LASTEXITCODE -ne 0) { throw 'Frozen payload validation failed' }
  & $venvPython scripts\package_local_bundle.py --launcher-dir dist --artifacts $artifacts --output $OutputZip
  if ($LASTEXITCODE -ne 0) { throw 'Local complete ZIP packaging failed' }
} finally {
  Pop-Location
}

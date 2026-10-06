#Requires -Version 7.3
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

# The host runner has no Python or Node. Keep all tools inside this checkout.
$Tools = Join-Path (Split-Path -Parent $PSScriptRoot) ".ci-tools"
New-Item -ItemType Directory -Force $Tools | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:UV_PYTHON_BIN_DIR = Join-Path $Tools "python-bin"
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"

$UvVersion = "0.12.23"
$UvName = "uv-x86_64-pc-windows-msvc.zip"
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvName"
$UvArchive = Join-Path $Tools $UvName
Invoke-WebRequest $UvUrl -OutFile $UvArchive
$UvChecksum = "$UvArchive.sha256"
Invoke-WebRequest "$UvUrl.sha256" -OutFile $UvChecksum
$ExpectedUvHash = ((Get-Content $UvChecksum -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash $UvArchive -Algorithm SHA256).Hash -ine $ExpectedUvHash) {
    throw "uv archive checksum mismatch"
}
Expand-Archive $UvArchive (Join-Path $Tools "uv") -Force
$Uv = Join-Path $Tools "uv\uv.exe"
& $Uv python install 3.12
& $Uv venv --python 3.12 (Join-Path (Split-Path -Parent $PSScriptRoot) ".venv") --seed

# Run the official v3 artifact uploader explicitly using a portable Node runtime.
$NodeVersion = "22.23.3"
$NodeName = "node-v$NodeVersion-win-x64.zip"
$NodeUrl = "https://nodejs.org/dist/v$NodeVersion"
$NodeArchive = Join-Path $Tools $NodeName
Invoke-WebRequest "$NodeUrl/$NodeName" -OutFile $NodeArchive
$NodeChecksums = Join-Path $Tools "SHASUMS256.txt"
Invoke-WebRequest "$NodeUrl/SHASUMS256.txt" -OutFile $NodeChecksums
$Checksums = Get-Content $NodeChecksums -Raw
$ChecksumLine = ($Checksums -split '\r?\n' | Where-Object { $_ -match "  $([regex]::Escape($NodeName))$" })
if (-not $ChecksumLine) { throw "Node archive checksum missing" }
$ExpectedNodeHash = ($ChecksumLine -split '\s+')[0]
if ((Get-FileHash $NodeArchive -Algorithm SHA256).Hash -ine $ExpectedNodeHash) {
    throw "Node archive checksum mismatch"
}
Expand-Archive $NodeArchive $Tools -Force
$Uploader = Join-Path $Tools "upload-artifact"
git init $Uploader
git -C $Uploader remote add origin https://github.com/actions/upload-artifact.git
git -C $Uploader fetch --depth 1 origin ff15f0306b3f739f7b6fd43fb5d26cd321bd4de5
git -C $Uploader checkout --detach FETCH_HEAD

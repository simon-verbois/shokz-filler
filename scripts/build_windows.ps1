#Requires -Version 7.3
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$ProgressPreference = "SilentlyContinue"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.12 -m venv .venv
    } else {
        python -m venv .venv
    }
}
$env:QT_QPA_PLATFORM = "offscreen"
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install ".[dev]"

# Fail on tests before downloading/extracting the large media runtime archives.
& .venv\Scripts\python.exe -m pytest
& .venv\Scripts\python.exe -m ruff check .
& .venv\Scripts\python.exe -m mypy

$BinDir = "src\shokz_refill\bin"
New-Item -ItemType Directory -Force $BinDir | Out-Null
if (-not (Test-Path "$BinDir\ffmpeg.exe") -or -not (Test-Path "$BinDir\ffprobe.exe")) {
    $Archive = Join-Path $env:TEMP "shokz-refill-ffmpeg.zip"
    $Extract = Join-Path $env:TEMP "shokz-refill-ffmpeg"
    Write-Host "Downloading ffmpeg Windows runtime"
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $Archive
    Remove-Item $Extract -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Extracting ffmpeg Windows runtime"
    Expand-Archive $Archive $Extract
    $Release = Get-ChildItem $Extract -Directory | Select-Object -First 1
    Copy-Item "$($Release.FullName)\bin\ffmpeg.exe" "$BinDir\ffmpeg.exe"
    Copy-Item "$($Release.FullName)\bin\ffprobe.exe" "$BinDir\ffprobe.exe"
    $License = Get-ChildItem $Release.FullName -Recurse -File | Where-Object { $_.Name -match "(?i)license" } | Select-Object -First 1
    if ($License) { Copy-Item $License.FullName "$BinDir\FFMPEG-GPLv3.txt" }
}
if (-not (Test-Path "$BinDir\deno.exe")) {
    $DenoArchive = Join-Path $env:TEMP "shokz-refill-deno.zip"
    $DenoExtract = Join-Path $env:TEMP "shokz-refill-deno"
    Write-Host "Downloading Deno Windows runtime"
    Invoke-WebRequest "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" -OutFile $DenoArchive
    Remove-Item $DenoExtract -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive $DenoArchive $DenoExtract
    Copy-Item "$DenoExtract\deno.exe" "$BinDir\deno.exe"
}
if (-not (Test-Path "$BinDir\DENO-LICENSE.md")) {
    Invoke-WebRequest "https://raw.githubusercontent.com/denoland/deno/main/LICENSE.md" -OutFile "$BinDir\DENO-LICENSE.md"
}

& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean shokz-refill.spec
$Artifact = "dist\Shokz-Refill-windows-x86_64.exe"
Move-Item "dist\Shokz-Refill.exe" $Artifact -Force
$SmokeTest = Start-Process -FilePath (Join-Path $ProjectDir $Artifact) -ArgumentList "--smoke-test" -Wait -PassThru
if ($SmokeTest.ExitCode -ne 0) { throw "Packaged application smoke test failed ($($SmokeTest.ExitCode))" }
$Hash = (Get-FileHash $Artifact -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path "$Artifact.sha256" -Value "$Hash  Shokz-Refill-windows-x86_64.exe"
Write-Host "Portable Windows executable: $Artifact"

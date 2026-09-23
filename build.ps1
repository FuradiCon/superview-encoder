# Builds dist\Superview Encoder\ and Superview Encoder.zip
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".venv\Scripts\python.exe"

& $py -m pytest -m "not slow" -q
if ($LASTEXITCODE -ne 0) { throw "unit tests failed" }
foreach ($f in "ffmpeg\ffmpeg.exe", "ffmpeg\ffprobe.exe", "assets\icon.ico") {
    if (-not (Test-Path $f)) { throw "missing $f" }
}

& $py -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name "Superview Encoder" --icon assets\icon.ico `
    --add-data "ui;ui" --add-data "ffmpeg;ffmpeg" --add-data "assets\icon.ico;assets" `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$out = "dist\Superview Encoder"
Copy-Item dist-extras\README.txt $out
Copy-Item dist-extras\LICENSES $out -Recurse -Force

if (Test-Path "Superview Encoder.zip") { Remove-Item "Superview Encoder.zip" }
Compress-Archive -Path $out -DestinationPath "Superview Encoder.zip"
$mb = [math]::Round((Get-ChildItem $out -Recurse | Measure-Object Length -Sum).Sum / 1MB)
$zmb = [math]::Round((Get-Item "Superview Encoder.zip").Length / 1MB)
"Built: $out ($mb MB), zip $zmb MB"

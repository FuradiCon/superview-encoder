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
# Files unzipped from a download carry Windows' "from the internet" mark, and
# .NET Framework refuses to load marked DLLs -- which kills pywebview (pythonnet)
# at startup. This config tells .NET to trust the app's own bundled DLLs.
Copy-Item dist-extras\app.exe.config "$out\Superview Encoder.exe.config"

# Self-test a copy that looks freshly downloaded: every file marked as internet zone.
$dl = Join-Path $env:TEMP "sv-build-selftest\Superview Encoder"
Remove-Item (Split-Path $dl) -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $out $dl -Recurse
$zone = "[ZoneTransfer]`r`nZoneId=3`r`nHostUrl=https://github.com/"
Get-ChildItem $dl -Recurse -File | ForEach-Object { Set-Content -Path $_.FullName -Stream Zone.Identifier -Value $zone }
$result = Join-Path $env:TEMP "superview-selftest.json"
Remove-Item $result -ErrorAction SilentlyContinue
$p = Start-Process "$dl\Superview Encoder.exe" -ArgumentList "--self-test" -PassThru
if (-not $p.WaitForExit(120000)) { Stop-Process -Id $p.Id -Force; throw "self-test hung (error dialog?) on the downloaded-style copy" }
if ($p.ExitCode -ne 0) { Get-Content $result -ErrorAction SilentlyContinue; throw "self-test failed on the downloaded-style copy" }
"Self-test passed on a downloaded-style copy: " + ((Get-Content $result -Raw | ConvertFrom-Json).encoder)
Remove-Item (Split-Path $dl) -Recurse -Force

if (Test-Path "Superview Encoder.zip") { Remove-Item "Superview Encoder.zip" }
Compress-Archive -Path $out -DestinationPath "Superview Encoder.zip"
$mb = [math]::Round((Get-ChildItem $out -Recurse | Measure-Object Length -Sum).Sum / 1MB)
$zmb = [math]::Round((Get-Item "Superview Encoder.zip").Length / 1MB)
"Built: $out ($mb MB), zip $zmb MB"

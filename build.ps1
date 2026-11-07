# Arma TasloStacks.exe (PyInstaller, carpeta dist\TasloStacks) y el instalador (Inno Setup, installer\Output).
# Uso: .\build.ps1          (desde la carpeta del proyecto, con Python 3.12 y "pip install -r requirements.txt pyinstaller")
$ErrorActionPreference = "Continue"  # PyInstaller escribe su log en stderr; con "Stop" PowerShell lo toma como error
Set-Location $PSScriptRoot
$version = (Select-String -Path "taslostacks\__init__.py" -Pattern 'VERSION = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "TasloStacks $version" -ForegroundColor Cyan

# 0) la página no puede tener errores de JavaScript: la app se queda en la pantalla de carga
python scripts/revisar_js.py
if ($LASTEXITCODE -ne 0) { throw "La plantilla tiene un error de JavaScript" }

# 1) exe
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
if (Test-Path build) { Remove-Item build -Recurse -Force }
python -m PyInstaller --noconfirm --clean --windowed --name TasloStacks --icon assets\icon.ico `
    --add-data "assets;assets" `
    --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.winforms --hidden-import clr `
    --collect-all webview --collect-submodules psutil `
    TasloStacks.pyw 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern "ERROR|WARNING: Hidden|completed successfully|Building EXE" 
if ($LASTEXITCODE -ne 0 -or -not (Test-Path "dist\TasloStacks\TasloStacks.exe")) { throw "PyInstaller falló (código $LASTEXITCODE)" }
Write-Host "exe listo: dist\TasloStacks\TasloStacks.exe" -ForegroundColor Green

# 2) instalador
$iscc = @("C:\Program Files (x86)\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Warning "No encontré Inno Setup 6 (ISCC.exe): queda solo la carpeta dist\TasloStacks"; exit 0 }
& $iscc "/DAppVersion=$version" "installer\TasloStacks.iss" 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falló (código $LASTEXITCODE)" }
Write-Host "instalador listo: installer\Output\TasloStacks-Setup-$version.exe" -ForegroundColor Green

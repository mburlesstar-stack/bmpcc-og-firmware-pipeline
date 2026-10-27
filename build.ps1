# Build a standalone Windows executable with PyInstaller.
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name "BMPCC-Firmware-Patcher" `
        --collect-submodules bmpcc_pipeline --paths . main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    Write-Host "Built dist\BMPCC-Firmware-Patcher.exe"
} finally {
    Pop-Location
}

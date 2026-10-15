param([string]$BuildPython = "python", [switch]$SkipModel)
$ErrorActionPreference = 'Stop'
$moduleRoot = $PSScriptRoot
$runtimeRoot = Join-Path $moduleRoot 'runtime'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
if (!(Test-Path (Join-Path $runtimeRoot 'python.exe'))) {
    $archive = Join-Path $moduleRoot 'python-embed.zip'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $runtimeRoot -Force
    Remove-Item -LiteralPath $archive
}
@"
python312.zip
.
Lib/site-packages
..
import site
"@ | Set-Content -LiteralPath (Join-Path $runtimeRoot 'python312._pth') -Encoding ascii
& (Join-Path $runtimeRoot 'python.exe') -c 'import numpy, PIL.Image, onnxruntime' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $BuildPython -m pip install --disable-pip-version-check --only-binary=:all: --upgrade --target (Join-Path $runtimeRoot 'Lib/site-packages') -r (Join-Path $moduleRoot 'requirements-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
}
if (!$SkipModel) {
    $modelFile = Join-Path $moduleRoot 'models/birefnet-lite-512-native-fp16.onnx'
    $manifestFile = Join-Path $moduleRoot 'models/manifest.json'
    $needsModelBuild = !(Test-Path $modelFile) -or !(Test-Path $manifestFile)
    if (!$needsModelBuild) {
        $modelManifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
        $needsModelBuild = (Get-FileHash -LiteralPath $modelFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modelManifest.sha256
    }
    if ($needsModelBuild) {
        & $BuildPython -m pip install --disable-pip-version-check --only-binary=:all: --no-deps --target (Join-Path $moduleRoot 'tools/build-libs') onnx==1.18.0 typing_extensions==4.16.0
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las herramientas de reconstruccion.' }
    }
    & (Join-Path $runtimeRoot 'python.exe') (Join-Path $moduleRoot 'tools/download_model.py')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar/verificar el modelo.' }
}
& (Join-Path $runtimeRoot 'python.exe') (Join-Path $moduleRoot 'backend/engine.py') --doctor
if ($LASTEXITCODE -ne 0) { throw 'Fallo la verificacion del motor.' }

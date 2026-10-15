param([Parameter(Mandatory=$true)][string]$GimpProfile)
$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$profileRoot = [IO.Path]::GetFullPath($GimpProfile)
$destination = Join-Path $profileRoot 'plug-ins\smart-subject'
if ($sourceRoot -eq $destination) { Write-Output 'El modulo ya esta instalado en este perfil.'; exit 0 }
if ($destination.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'El destino no puede estar dentro de la carpeta de origen.'
}
if (Test-Path -LiteralPath $destination) { throw 'Ya existe smart-subject en el destino. Conserva o renombra esa copia antes de instalar.' }
New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
Copy-Item -LiteralPath $sourceRoot -Destination $destination -Recurse
& (Join-Path $destination 'runtime\python.exe') (Join-Path $destination 'backend\engine.py') --doctor
if ($LASTEXITCODE -ne 0) { throw 'La copia no supero la verificacion.' }
Write-Output "Instalado: $destination. Reinicia GIMP."

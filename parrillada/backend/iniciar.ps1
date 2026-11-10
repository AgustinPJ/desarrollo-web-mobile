# Levanta los 7 servicios del backend, cada uno en su propia ventana (como en clases).
# Antes: Mongo corriendo, Vault en modo dev corriendo y secretos cargados (python vault/cargar_secretos.py).
# Uso:  .\iniciar.ps1      (desde la carpeta parrillada\backend)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot

$python = Join-Path $raiz "..\..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$archivoTokens = Join-Path $raiz ".tokens"
if (-not (Test-Path $archivoTokens)) {
    throw "No existe .tokens. Primero ejecute: python vault/cargar_secretos.py"
}
$tokens = @{}
foreach ($linea in Get-Content $archivoTokens) {
    $partes = $linea.Split("=", 2)
    if ($partes.Length -eq 2) { $tokens[$partes[0]] = $partes[1] }
}

if (-not $env:VAULT_ADDR) { $env:VAULT_ADDR = "http://127.0.0.1:8200" }
$tokenOriginal = $env:VAULT_TOKEN

# Todos escuchan SOLO en 127.0.0.1. El gateway es el único que se usa desde afuera.
$servicios = @(
    @{ nombre = "clients";   puerto = 9004 },
    @{ nombre = "auth";      puerto = 8100 },
    @{ nombre = "inventory"; puerto = 9001 },
    @{ nombre = "orders";    puerto = 9002 },
    @{ nombre = "payments";  puerto = 9003 },
    @{ nombre = "gateway";   puerto = 8000 }
)

foreach ($s in $servicios) {
    # El token de Vault se pasa por variable de entorno (la hereda la ventana nueva), no por la línea de comandos.
    $env:VAULT_TOKEN = $tokens[$s.nombre]
    $carpeta = Join-Path $raiz "services\$($s.nombre)"
    $comando = "`$host.UI.RawUI.WindowTitle = '$($s.nombre) :$($s.puerto)'; " +
               "& '$python' -m uvicorn main:app --host 127.0.0.1 --port $($s.puerto)"
    Start-Process powershell -WorkingDirectory $carpeta -ArgumentList "-NoExit", "-Command", $comando
    Write-Host "[ok] $($s.nombre) iniciando en 127.0.0.1:$($s.puerto)"
}

$env:VAULT_TOKEN = $tokens["graphql"]
$carpeta = Join-Path $raiz "services\graphql"
Start-Process powershell -WorkingDirectory $carpeta -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'graphql :4000'; node server.js"
Write-Host "[ok] graphql iniciando en 127.0.0.1:4000"

$env:VAULT_TOKEN = $tokenOriginal

# Health checks
Start-Sleep -Seconds 6
$puertos = @{ gateway = 8000; auth = 8100; clients = 9004; inventory = 9001; orders = 9002; payments = 9003; graphql = 4000 }
foreach ($nombre in $puertos.Keys) {
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$($puertos[$nombre])/health" -TimeoutSec 3
        Write-Host "[health] $nombre -> $($r.status)"
    } catch {
        Write-Host "[health] $nombre -> NO RESPONDE (revise su ventana)" -ForegroundColor Red
    }
}

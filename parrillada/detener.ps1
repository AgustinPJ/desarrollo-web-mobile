# Detiene los servicios del backend (cierra los procesos que escuchan en sus puertos).
# Uso:  .\detener.ps1      (Vault y Mongo no se detienen aquí)

$puertos = 8000, 8100, 9001, 9002, 9003, 9004, 4000
foreach ($puerto in $puertos) {
    $conexiones = Get-NetTCPConnection -LocalPort $puerto -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conexiones) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "[ok] detenido el proceso del puerto $puerto"
    }
}

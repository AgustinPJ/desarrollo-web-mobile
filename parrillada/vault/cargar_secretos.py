"""
Carga (o rota) todos los secretos de integración en Vault.

- Genera un secreto distinto por cada tramo "llamador -> servicio".
- Guarda en secret/parrillada/<servicio> SOLO lo que ese servicio necesita.
- Crea una política por servicio que solo puede LEER su propia ruta.
- Crea un token por servicio con esa política y lo escribe en parrillada/.tokens
  (archivo local, está en .gitignore; nunca se sube al repo).

Uso (con Vault en modo dev ya corriendo):
    $env:VAULT_ADDR="http://127.0.0.1:8200"
    $env:VAULT_TOKEN="<token root de desarrollo>"
    python vault/cargar_secretos.py

Volver a ejecutarlo ROTA todos los secretos y tokens: los anteriores dejan de servir
(los tokens viejos se revocan). Después hay que reiniciar los servicios.
"""
import os
import secrets
import sys
from pathlib import Path

import httpx

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
ARCHIVO_TOKENS = Path(__file__).resolve().parent.parent / ".tokens"

# Tramos de comunicación permitidos: (quien llama, a quien llama).
# Si un tramo no está en esta lista, no existe secreto para él y el servicio destino lo rechaza.
TRAMOS = [
    ("gateway", "auth"),
    ("gateway", "clients"),
    ("gateway", "inventory"),
    ("gateway", "orders"),
    ("gateway", "payments"),
    ("gateway", "graphql"),
    ("auth", "clients"),         # al registrarse se crea el perfil del cliente
    ("orders", "inventory"),     # reservar y liberar stock
    ("payments", "orders"),      # leer el total y marcar el pedido como pagado
    ("graphql", "orders"),       # agregaciones
    ("graphql", "inventory"),
    ("graphql", "clients"),
]

SERVICIOS = ["gateway", "auth", "clients", "inventory", "orders", "payments", "graphql", "proveedor"]


def construir_secretos():
    por_servicio = {s: {} for s in SERVICIOS}
    for origen, destino in TRAMOS:
        valor = secrets.token_urlsafe(32)
        por_servicio[origen][f"salida_{destino}"] = valor    # lo envía el que llama
        por_servicio[destino][f"entrada_{origen}"] = valor   # lo verifica el que recibe

    # Clave de firma del webhook: la conocen solo el proveedor de pagos (simulado) y payments.
    clave_webhook = secrets.token_urlsafe(32)
    por_servicio["payments"]["clave_webhook"] = clave_webhook
    por_servicio["proveedor"]["clave_webhook"] = clave_webhook
    return por_servicio


def main():
    if not VAULT_TOKEN:
        sys.exit("Falta la variable VAULT_TOKEN (token root de desarrollo)")

    cabeceras = {"X-Vault-Token": VAULT_TOKEN}
    try:
        cliente = httpx.Client(base_url=VAULT_ADDR, headers=cabeceras, timeout=5.0)
        cliente.get("/v1/sys/health").raise_for_status()
    except httpx.HTTPError:
        sys.exit(f"No fue posible conectar con Vault en {VAULT_ADDR}")

    # Revocar los tokens de la carga anterior (si existe el archivo).
    if ARCHIVO_TOKENS.exists():
        for linea in ARCHIVO_TOKENS.read_text(encoding="utf-8").splitlines():
            if "=" in linea:
                token_viejo = linea.split("=", 1)[1].strip()
                cliente.post("/v1/auth/token/revoke", json={"token": token_viejo})

    tokens = {}
    for servicio, datos in construir_secretos().items():
        ruta = f"parrillada/{servicio}"

        # 1. Secretos del servicio (KV versión 2).
        r = cliente.post(f"/v1/secret/data/{ruta}", json={"data": datos})
        r.raise_for_status()

        # 2. Política de mínimo privilegio: solo lectura de su propia ruta.
        politica = f'path "secret/data/{ruta}" {{ capabilities = ["read"] }}'
        r = cliente.put(f"/v1/sys/policies/acl/{servicio}", json={"policy": politica})
        r.raise_for_status()

        # 3. Token del servicio con esa política, válido por 24 horas.
        r = cliente.post("/v1/auth/token/create", json={
            "policies": [servicio],
            "display_name": servicio,
            "ttl": "24h",
            "renewable": False,
        })
        r.raise_for_status()
        tokens[servicio] = r.json()["auth"]["client_token"]
        print(f"[ok] {ruta}: {len(datos)} secretos (valores no se muestran)")

    lineas = [f"{servicio}={token}" for servicio, token in tokens.items()]
    ARCHIVO_TOKENS.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"[ok] tokens por servicio guardados en {ARCHIVO_TOKENS.name} (no se sube al repo)")


if __name__ == "__main__":
    main()

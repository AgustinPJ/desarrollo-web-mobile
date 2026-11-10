"""
Utilidades compartidas por las pruebas. Las pruebas se ejecutan contra el backend REAL levantado
(gateway en 127.0.0.1:8000), no contra simulaciones.

Requisitos antes de ejecutar:
    - Servicios levantados con iniciar.ps1
    - $env:OPERADOR_PASSWORD con la misma clave usada en datos/cargar_datos.py
Ejecutar:  python -m pytest tests -v
"""
import hashlib
import hmac
import json
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
ARCHIVO_TOKENS = Path(__file__).resolve().parent.parent / ".tokens"
SERVICIOS_DIRECTOS = {
    "auth": "http://127.0.0.1:8100",
    "clients": "http://127.0.0.1:9004",
    "inventory": "http://127.0.0.1:9001",
    "orders": "http://127.0.0.1:9002",
    "payments": "http://127.0.0.1:9003",
    "graphql": "http://127.0.0.1:4000",
}


def token_vault(servicio):
    for linea in ARCHIVO_TOKENS.read_text(encoding="utf-8").splitlines():
        if linea.startswith(servicio + "="):
            return linea.split("=", 1)[1].strip()
    raise RuntimeError(f"No hay token para {servicio}; ejecute vault/cargar_secretos.py")


@pytest.fixture(scope="session")
def api():
    with httpx.Client(base_url=GATEWAY, timeout=10.0) as cliente:
        yield cliente


def registrar_y_entrar(api, nombre):
    correo = f"{nombre.split()[0].lower()}.{uuid.uuid4().hex[:8]}@correo.cl"
    clave = "ClaveSegura123"
    r = api.post("/api/v1/auth/registro", json={
        "nombre": nombre, "correo": correo, "direccion": "Av. Las Parcelas 1234", "password": clave})
    assert r.status_code == 201, r.text
    r = api.post("/api/v1/auth/login", json={"correo": correo, "password": clave})
    assert r.status_code == 200, r.text
    return {"correo": correo, "clave": clave, "user_id": None,
            "headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


@pytest.fixture(scope="session")
def cliente_a(api):
    usuario = registrar_y_entrar(api, "Carlos Silva")
    usuario["user_id"] = api.get("/api/v1/clientes/me", headers=usuario["headers"]).json()["user_id"]
    return usuario


@pytest.fixture(scope="session")
def cliente_b(api):
    usuario = registrar_y_entrar(api, "Ana Rojas")
    usuario["user_id"] = api.get("/api/v1/clientes/me", headers=usuario["headers"]).json()["user_id"]
    return usuario


@pytest.fixture(scope="session")
def operador(api):
    clave = os.getenv("OPERADOR_PASSWORD")
    if not clave:
        pytest.skip("Defina OPERADOR_PASSWORD para las pruebas de operador")
    correo = os.getenv("OPERADOR_CORREO", "operador@tiendadelfuego.cl")
    r = api.post("/api/v1/auth/login", json={"correo": correo, "password": clave})
    assert r.status_code == 200, r.text
    return {"headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


def fecha_entrega():
    return (date.today() + timedelta(days=2)).isoformat()


def crear_pedido(api, usuario, producto_id="SMOK-02", cantidad=1, **extra):
    cuerpo = {"items": [{"producto_id": producto_id, "cantidad": cantidad}],
              "direccion_entrega": "Av. Las Parcelas 1234", "fecha_entrega": fecha_entrega()}
    cuerpo.update(extra)
    return api.post("/api/v1/pedidos", json=cuerpo, headers=usuario["headers"])


def clave_webhook():
    """El proveedor simulado lee la clave de firma desde Vault con SU token (solo puede leer su ruta)."""
    r = httpx.get(f"{VAULT_ADDR}/v1/secret/data/parrillada/proveedor",
                  headers={"X-Vault-Token": token_vault("proveedor")}, timeout=5.0)
    r.raise_for_status()
    return r.json()["data"]["data"]["clave_webhook"]


def enviar_webhook(api, evento, clave=None):
    """Simula al proveedor de pagos: firma el cuerpo con HMAC-SHA256 y lo envía al gateway."""
    cuerpo = json.dumps(evento).encode()
    firma = hmac.new((clave or clave_webhook()).encode(), cuerpo, hashlib.sha256).hexdigest()
    return api.post("/api/v1/pagos/webhook", content=cuerpo,
                    headers={"content-type": "application/json", "X-Firma": firma})


@pytest.fixture(scope="session", autouse=True)
def reponer_stock(api, operador):
    """Las pruebas compran productos: antes de empezar se repone el stock (PARR-03 se deja en 0 a propósito)."""
    for producto_id in ["PARR-01", "PARR-02", "SMOK-01", "SMOK-02", "PACK-01", "PACK-02"]:
        r = api.patch(f"/api/v1/productos/{producto_id}/stock", json={"stock": 200}, headers=operador["headers"])
        assert r.status_code == 200, r.text

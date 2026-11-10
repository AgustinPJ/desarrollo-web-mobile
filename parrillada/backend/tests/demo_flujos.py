"""
Demostración de los flujos principales (M10), de punta a punta y por el API Gateway.
Imprime cada solicitud con su código de respuesta. Los tokens NO se imprimen.

Uso (con todo levantado):
    $env:OPERADOR_PASSWORD="..."
    python tests/demo_flujos.py
"""
import json
import os
import uuid
from datetime import date, timedelta

import httpx

from conftest import GATEWAY, SERVICIOS_DIRECTOS, enviar_webhook


def mostrar(titulo, r, campos=None):
    datos = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    if isinstance(datos, dict) and campos:
        datos = {k: datos[k] for k in campos if k in datos}
    if isinstance(datos, dict) and "access_token" in datos:
        datos = {**datos, "access_token": "<oculto>"}
    texto = json.dumps(datos, ensure_ascii=False)
    print(f"\n[{r.status_code}] {titulo}")
    print("      " + (texto if len(texto) < 300 else texto[:300] + " ..."))


def cuenta_nueva(api, nombre):
    correo = f"{nombre.split()[0].lower()}.{uuid.uuid4().hex[:6]}@correo.cl"
    r = api.post("/api/v1/auth/registro", json={"nombre": nombre, "correo": correo,
                                                "direccion": "Av. Las Parcelas 1234", "password": "ClaveSegura123"})
    mostrar(f"S01 POST /api/v1/auth/registro ({nombre})", r)
    r = api.post("/api/v1/auth/login", json={"correo": correo, "password": "ClaveSegura123"})
    mostrar("S02 POST /api/v1/auth/login", r)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main():
    api = httpx.Client(base_url=GATEWAY, timeout=10.0)
    print("=== Flujo de compra: catálogo -> registro -> pedido -> pago -> despacho ===")

    r = api.get("/api/v1/productos", params={"linea": "Smoked & Ready"})
    mostrar("S08 GET /api/v1/productos?linea=Smoked & Ready (anónimo)", r)

    carlos = cuenta_nueva(api, "Carlos Silva")
    r = api.get("/api/v1/clientes/me", headers=carlos)
    mostrar("S04 GET /api/v1/clientes/me", r, ["nombre", "correo", "direccion"])

    pedido = {"items": [{"producto_id": "SMOK-02", "cantidad": 2}], "direccion_entrega": "Av. Las Parcelas 1234",
              "fecha_entrega": (date.today() + timedelta(days=2)).isoformat(), "total": 1}
    r = api.post("/api/v1/pedidos", json=pedido, headers={**carlos, "Idempotency-Key": uuid.uuid4().hex})
    mostrar("S13 POST /api/v1/pedidos (el navegador intenta mandar total=1)", r, ["id", "items", "total", "estado"])
    pedido_id = r.json()["id"]

    r = api.post("/api/v1/pagos", json={"order_id": pedido_id, "monto": 1}, headers=carlos)
    mostrar("S18 POST /api/v1/pagos (el navegador intenta mandar monto=1)", r, ["payment_id", "monto", "estado"])
    pago = r.json()

    evento = {"event_id": "evt-" + uuid.uuid4().hex[:10], "payment_id": pago["payment_id"],
              "estado": "aprobado", "monto": pago["monto"]}
    r = enviar_webhook(api, evento)
    mostrar("S20 POST /api/v1/pagos/webhook (proveedor, firma HMAC válida)", r)
    r = enviar_webhook(api, evento)
    mostrar("S20 POST /api/v1/pagos/webhook (MISMO evento repetido)", r)

    consulta = "{ misPedidos(limit: 5) { total items { id estado total items { nombre cantidad producto { linea disponible } } } } }"
    r = api.post("/api/v1/graphql", json={"query": consulta}, headers=carlos)
    mostrar("S22 POST /api/v1/graphql misPedidos (orders + inventory)", r)

    print("\n=== Controles de acceso ===")
    ana = cuenta_nueva(api, "Ana Rojas")
    r = api.get(f"/api/v1/pedidos/{pedido_id}", headers=carlos)
    mostrar("S15 GET /api/v1/pedidos/{id} por su DUEÑO (Carlos)", r, ["id", "estado", "total"])
    r = api.get(f"/api/v1/pedidos/{pedido_id}", headers=ana)
    mostrar("S15 GET /api/v1/pedidos/{id} por OTRA cuenta (Ana)", r)
    r = api.get("/api/v1/pedidos")
    mostrar("S14 GET /api/v1/pedidos sin sesión", r)
    r = api.post("/api/v1/productos", json={}, headers=ana)
    mostrar("S10 POST /api/v1/productos con rol cliente", r)
    r = api.get("/api/v1/clientes/me", headers={**ana, "X-User-Id": "otro-usuario", "X-User-Roles": "operador"})
    mostrar("S04 GET /api/v1/clientes/me con cabeceras X-User-* falsas (se descartan)", r, ["nombre"])
    r = httpx.get(SERVICIOS_DIRECTOS["orders"] + "/orders", headers={"X-User-Id": "x", "X-User-Roles": "operador"})
    mostrar("Acceso DIRECTO a orders (127.0.0.1:9002) sin secreto de tramo", r)
    r = api.delete(f"/api/v1/pedidos/{pedido_id}", headers=carlos)
    mostrar("DELETE /api/v1/pedidos/{id} (verbo no publicado)", r)

    print("\n=== Operador: despacho ===")
    r = api.post("/api/v1/auth/login", json={"correo": os.getenv("OPERADOR_CORREO", "operador@tiendadelfuego.cl"),
                                             "password": os.environ["OPERADOR_PASSWORD"]})
    mostrar("S02 POST /api/v1/auth/login (operador)", r)
    operador = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for estado in ["en_despacho", "entregado"]:
        r = api.patch(f"/api/v1/pedidos/{pedido_id}/estado", json={"estado": estado}, headers=operador)
        mostrar(f"S17 PATCH /api/v1/pedidos/{{id}}/estado -> {estado}", r, ["estado"])
    r = api.post(f"/api/v1/pedidos/{pedido_id}/anular", headers=carlos)
    mostrar("S16 POST /api/v1/pedidos/{id}/anular cuando ya fue entregado", r)

    print("\n=== Cierre de sesión ===")
    r = api.post("/api/v1/auth/logout", headers=carlos)
    mostrar("S03 POST /api/v1/auth/logout", r)
    r = api.get("/api/v1/clientes/me", headers=carlos)
    mostrar("S04 GET /api/v1/clientes/me con el token revocado", r)


if __name__ == "__main__":
    main()

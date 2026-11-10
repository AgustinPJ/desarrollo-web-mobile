"""
Prueba manual de indisponibilidad de una dependencia (M8 y M10).

Pasos:
  1. Con todo levantado, cerrar SOLO la ventana de inventory (Ctrl+C).
  2. $env:OPERADOR_PASSWORD="..." ; python tests/prueba_inventory_caido.py
  3. Volver a levantar inventory.

Resultado esperado:
  - Catálogo por el gateway: 503 controlado (sin detalles internos).
  - GraphQL: devuelve los datos de orders y un error PARCIAL en el campo "producto"
    (no presenta el fallo como si fueran datos completos).
"""
import json
import os

import httpx

GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")


def main():
    api = httpx.Client(base_url=GATEWAY, timeout=10.0)
    r = api.post("/api/v1/auth/login", json={"correo": os.getenv("OPERADOR_CORREO", "operador@tiendadelfuego.cl"),
                                             "password": os.environ["OPERADOR_PASSWORD"]})
    cabeceras = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = api.get("/api/v1/productos")
    print("GET /api/v1/productos ->", r.status_code, r.text)

    consulta = "{ analitica { topProductos { productoId unidades producto { nombre } } } }"
    r = api.post("/api/v1/graphql", json={"query": consulta}, headers=cabeceras)
    print("POST /api/v1/graphql ->", r.status_code)
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

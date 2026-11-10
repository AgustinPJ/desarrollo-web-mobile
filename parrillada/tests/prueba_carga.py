"""
Prueba de carga reproducible (M9). Mide latencia p50/p95, throughput y errores por el API Gateway.

Escenario (proyección para la tienda): 20 usuarios concurrentes durante 30 s consultando el catálogo
y 1 de cada 5 consultando "mis pedidos" por GraphQL.

Uso (con todo levantado y el gateway iniciado con un límite alto, para medir el sistema y no el rate limit):
    $env:LIMITE_POR_MINUTO="100000"   # en la ventana del gateway, antes de iniciarlo
    $env:OPERADOR_PASSWORD="..."
    python tests/prueba_carga.py --usuarios 20 --segundos 30
"""
import argparse
import asyncio
import os
import statistics
import time
import uuid

import httpx

GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")


async def preparar_cliente(api):
    correo = f"carga.{uuid.uuid4().hex[:8]}@correo.cl"
    await api.post("/api/v1/auth/registro", json={"nombre": "Usuario Carga", "correo": correo,
                                                  "direccion": "Calle Carga 123", "password": "ClaveCarga123"})
    r = await api.post("/api/v1/auth/login", json={"correo": correo, "password": "ClaveCarga123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def usuario_virtual(api, cabeceras, fin, latencias, errores, numero):
    consulta = {"query": "{ misPedidos(limit: 5) { total items { estado items { producto { nombre } } } } }"}
    i = 0
    while time.perf_counter() < fin:
        inicio = time.perf_counter()
        try:
            if numero % 5 == 0 and i % 2 == 0:
                r = await api.post("/api/v1/graphql", json=consulta, headers=cabeceras)
            else:
                r = await api.get("/api/v1/productos")
            if r.status_code >= 400:
                errores.append(r.status_code)
        except httpx.HTTPError:
            errores.append("conexion")
        latencias.append((time.perf_counter() - inicio) * 1000)
        i += 1


async def main(usuarios, segundos):
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=10.0,
                                 limits=httpx.Limits(max_connections=usuarios + 5)) as api:
        cabeceras = await preparar_cliente(api)
        latencias, errores = [], []
        inicio = time.perf_counter()
        fin = inicio + segundos
        await asyncio.gather(*[usuario_virtual(api, cabeceras, fin, latencias, errores, n) for n in range(usuarios)])
        duracion = time.perf_counter() - inicio

    latencias.sort()
    p95 = latencias[int(len(latencias) * 0.95) - 1]
    print("=== Resultado prueba de carga ===")
    print(f"Usuarios concurrentes : {usuarios}")
    print(f"Duración              : {duracion:.1f} s")
    print(f"Solicitudes           : {len(latencias)}")
    print(f"Throughput            : {len(latencias) / duracion:.1f} req/s")
    print(f"Latencia p50          : {statistics.median(latencias):.1f} ms")
    print(f"Latencia p95          : {p95:.1f} ms")
    print(f"Latencia máxima       : {latencias[-1]:.1f} ms")
    print(f"Errores               : {len(errores)} ({100 * len(errores) / max(len(latencias), 1):.2f} %)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--usuarios", type=int, default=20)
    parser.add_argument("--segundos", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(main(args.usuarios, args.segundos))

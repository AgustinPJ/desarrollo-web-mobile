"""
API Gateway (puerto 8000). ÚNICO servicio que se expone hacia afuera.

Qué hace en cada solicitud:
1. Asigna un X-Correlation-Id (o respeta el que viene) para seguirla en todos los logs.
2. Limita solicitudes por IP (rate limit) -> 429.
3. Busca la ruta en una LISTA EXPLÍCITA de rutas y verbos (no hay proxy genérico) -> 404 si no está.
4. Si la ruta no es anónima: exige Bearer token y lo valida con Auth Service (/introspect) -> 401.
5. Revisa el rol que exige la ruta -> 403.
6. Arma cabeceras NUEVAS hacia el servicio: su secreto de tramo (Vault) + identidad verificada.
   Las cabeceras X-User-* que mande el navegador se descartan (nunca se copian).
7. Reenvía con timeout y traduce fallos a errores controlados (503/504), sin detalles internos.
"""
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")

# Destinos internos permitidos (todos escuchan solo en 127.0.0.1).
SERVICIOS = {
    "auth": os.getenv("AUTH_URL", "http://127.0.0.1:8100"),
    "clients": os.getenv("CLIENTS_URL", "http://127.0.0.1:9004"),
    "inventory": os.getenv("INVENTORY_URL", "http://127.0.0.1:9001"),
    "orders": os.getenv("ORDERS_URL", "http://127.0.0.1:9002"),
    "payments": os.getenv("PAYMENTS_URL", "http://127.0.0.1:9003"),
    "graphql": os.getenv("GRAPHQL_URL", "http://127.0.0.1:4000"),
}

# Lista explícita de rutas: (verbo, ruta externa, servicio, ruta interna, acceso).
# acceso: "anonimo" | "autenticado" | "cliente" | "operador" | "proveedor"
RUTAS = [
    # S01-S03 identidad
    ("POST", "/api/v1/auth/registro", "auth", "/registro", "anonimo"),
    ("POST", "/api/v1/auth/login", "auth", "/login", "anonimo"),
    ("POST", "/api/v1/auth/logout", "auth", "/logout", "autenticado"),
    # S04-S07 clientes
    ("GET", "/api/v1/clientes/me", "clients", "/clientes/me", "autenticado"),
    ("PUT", "/api/v1/clientes/me", "clients", "/clientes/me", "autenticado"),
    ("GET", "/api/v1/clientes", "clients", "/clientes", "operador"),
    ("GET", "/api/v1/clientes/{id}", "clients", "/clientes/{id}", "operador"),
    # S08-S12 catálogo e inventario
    ("GET", "/api/v1/productos", "inventory", "/productos", "anonimo"),
    ("GET", "/api/v1/productos/{id}", "inventory", "/productos/{id}", "anonimo"),
    ("POST", "/api/v1/productos", "inventory", "/productos", "operador"),
    ("PUT", "/api/v1/productos/{id}", "inventory", "/productos/{id}", "operador"),
    ("PATCH", "/api/v1/productos/{id}/stock", "inventory", "/productos/{id}/stock", "operador"),
    # S13-S17 pedidos
    ("POST", "/api/v1/pedidos", "orders", "/orders", "cliente"),
    ("GET", "/api/v1/pedidos", "orders", "/orders", "autenticado"),
    ("GET", "/api/v1/pedidos/{id}", "orders", "/orders/{id}", "autenticado"),
    ("POST", "/api/v1/pedidos/{id}/anular", "orders", "/orders/{id}/anular", "autenticado"),
    ("PATCH", "/api/v1/pedidos/{id}/estado", "orders", "/orders/{id}/estado", "operador"),
    # S18-S21 pagos
    ("POST", "/api/v1/pagos", "payments", "/pagos", "cliente"),
    ("GET", "/api/v1/pagos/{id}", "payments", "/pagos/{id}", "autenticado"),
    ("POST", "/api/v1/pagos/webhook", "payments", "/pagos/webhook", "proveedor"),
    ("POST", "/api/v1/pagos/{id}/reintentar-aviso", "payments", "/pagos/{id}/reintentar-aviso", "operador"),
    # S22 agregaciones GraphQL (privado, solo a través del gateway)
    ("POST", "/api/v1/graphql", "graphql", "/graphql", "autenticado"),
]

# Rate limit simple en memoria: máximo de solicitudes por IP por ventana de 60 s.
LIMITE_GENERAL = int(os.getenv("LIMITE_POR_MINUTO", "300"))
LIMITE_LOGIN = int(os.getenv("LIMITE_LOGIN_POR_MINUTO", "10"))
VENTANA_SEGUNDOS = 60
contador_solicitudes = {}

TIMEOUT = httpx.Timeout(5.0)
SECRETOS = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")


async def leer_secretos_vault():
    if not VAULT_TOKEN:
        raise RuntimeError("VAULT_TOKEN no está configurado")
    url = f"{VAULT_ADDR}/v1/secret/data/parrillada/gateway"
    try:
        async with httpx.AsyncClient(timeout=5.0) as cliente:
            respuesta = await cliente.get(url, headers={"X-Vault-Token": VAULT_TOKEN})
    except httpx.RequestError:
        raise RuntimeError("No fue posible conectar con Vault")
    if respuesta.status_code != 200:
        raise RuntimeError("No fue posible leer los secretos desde Vault")
    return respuesta.json()["data"]["data"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Los secretos se leen al arrancar y quedan en memoria: si Vault cae después,
    # el gateway sigue funcionando; si Vault no responde al arrancar, el gateway no inicia.
    SECRETOS.update(await leer_secretos_vault())
    yield


app = FastAPI(title="API Gateway - La Tienda del Fuego", lifespan=lifespan)


def buscar_ruta(metodo: str, ruta: str):
    """Compara segmento por segmento. {id} acepta un valor simple (sin / ni ..)."""
    partes = ruta.rstrip("/").split("/")
    for verbo, externa, servicio, interna, acceso in RUTAS:
        if verbo != metodo:
            continue
        partes_patron = externa.split("/")
        if len(partes_patron) != len(partes):
            continue
        parametros = {}
        coincide = True
        for patron, valor in zip(partes_patron, partes):
            if patron.startswith("{"):
                if not valor or valor in (".", "..") or len(valor) > 64:
                    coincide = False
                    break
                parametros[patron[1:-1]] = valor
            elif patron != valor:
                coincide = False
                break
        if coincide:
            return servicio, interna.format(**parametros), acceso
    return None


def excede_limite(ip: str, ruta: str) -> bool:
    ahora = time.time()
    clave = (ip, "login" if ruta.endswith("/auth/login") else "general")
    limite = LIMITE_LOGIN if clave[1] == "login" else LIMITE_GENERAL
    recientes = [t for t in contador_solicitudes.get(clave, []) if ahora - t < VENTANA_SEGUNDOS]
    recientes.append(ahora)
    contador_solicitudes[clave] = recientes
    return len(recientes) > limite


def error(status: int, detalle: str, correlation_id: str):
    return JSONResponse(status_code=status, content={"detail": detalle, "correlation_id": correlation_id},
                        headers={"X-Correlation-Id": correlation_id})


def cabeceras_internas(servicio: str, correlation_id: str):
    return {
        "X-Service-Name": "gateway",
        "X-Service-Secret": SECRETOS[f"salida_{servicio}"],
        "X-Correlation-Id": correlation_id,
    }


async def introspeccion(token: str, correlation_id: str):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
            respuesta = await cliente.post(f"{SERVICIOS['auth']}/introspect", json={"token": token},
                                           headers=cabeceras_internas("auth", correlation_id))
    except httpx.RequestError:
        return None
    if respuesta.status_code != 200:
        return None
    return respuesta.json()


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}


@app.api_route("/api/v1/{resto:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def entrada(request: Request, resto: str):
    inicio = time.time()
    correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    if len(correlation_id) > 64:
        correlation_id = str(uuid.uuid4())
    ip = request.client.host if request.client else "desconocida"
    usuario_log = "-"

    def registrar(status: int):
        # Log sin tokens, sin cuerpos ni datos personales: solo lo necesario para trazar.
        ms = int((time.time() - inicio) * 1000)
        log.info("cid=%s ip=%s %s %s -> %s %sms user=%s", correlation_id, ip, request.method,
                 request.url.path, status, ms, usuario_log)

    if excede_limite(ip, request.url.path):
        registrar(429)
        return error(429, "Demasiadas solicitudes, intente en un minuto", correlation_id)

    encontrada = buscar_ruta(request.method, request.url.path)
    if encontrada is None:
        registrar(404)
        return error(404, "Ruta no disponible", correlation_id)
    servicio, ruta_interna, acceso = encontrada

    cabeceras = cabeceras_internas(servicio, correlation_id)
    token = None

    autorizacion = request.headers.get("authorization", "")
    tiene_token = autorizacion.lower().startswith("bearer ")
    if acceso not in ("anonimo", "proveedor") and not tiene_token:
        registrar(401)
        return error(401, "Sesión requerida", correlation_id)

    # En rutas anónimas el token es opcional: si viene y es válido, se usa (ej. el operador ve el stock).
    if tiene_token and acceso != "proveedor":
        token = autorizacion[7:].strip()
        identidad = await introspeccion(token, correlation_id)
        if identidad is None:
            registrar(503)
            return error(503, "Servicio de autenticación no disponible", correlation_id)
        if identidad.get("active"):
            roles = identidad.get("roles", [])
            usuario_log = identidad["user_id"]
            # Identidad VERIFICADA: la arma el gateway, nunca se copia del navegador.
            cabeceras["X-User-Id"] = identidad["user_id"]
            cabeceras["X-User-Roles"] = ",".join(roles)
        elif acceso != "anonimo":
            registrar(401)
            return error(401, "Sesión inválida o vencida", correlation_id)

    if acceso in ("cliente", "operador") and acceso not in cabeceras.get("X-User-Roles", "").split(","):
        registrar(403)
        return error(403, "No tiene permiso para esta operación", correlation_id)

    # Solo se copian las cabeceras necesarias; todo lo demás (incluido X-User-*) se descarta.
    for nombre in ("content-type", "idempotency-key"):
        if nombre in request.headers:
            cabeceras[nombre] = request.headers[nombre]
    if acceso == "proveedor" and "x-firma" in request.headers:
        cabeceras["X-Firma"] = request.headers["x-firma"]

    cuerpo = await request.body()
    if servicio == "auth" and ruta_interna == "/logout":
        cabeceras["content-type"] = "application/json"
        cuerpo = json.dumps({"token": token}).encode()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
            respuesta = await cliente.request(request.method, SERVICIOS[servicio] + ruta_interna,
                                              params=request.query_params, content=cuerpo, headers=cabeceras)
    except httpx.TimeoutException:
        registrar(504)
        return error(504, "El servicio tardó demasiado en responder", correlation_id)
    except httpx.RequestError:
        registrar(503)
        return error(503, "Servicio no disponible", correlation_id)

    registrar(respuesta.status_code)
    salida = {"X-Correlation-Id": correlation_id}
    if "content-type" in respuesta.headers:
        salida["content-type"] = respuesta.headers["content-type"]
    return Response(content=respuesta.content, status_code=respuesta.status_code, headers=salida)

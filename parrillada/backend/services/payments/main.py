"""
payments (puerto 9003, red privada).
Inicia pagos y procesa el aviso (webhook) del proveedor de pagos.

Reglas clave:
- El monto SIEMPRE se lee desde orders; nunca se acepta un monto enviado por el navegador.
- El webhook se acepta solo con firma HMAC-SHA256 válida (clave compartida con el proveedor, en Vault).
- Idempotencia: cada evento del proveedor se procesa una sola vez (índice único en event_id).
- Solo payments, con su secreto de tramo, puede avisar a orders que un pedido quedó pagado.
Proveedor: adaptador de prueba (sandbox simulado) que respeta el contrato de un proveedor real.
"""
import hashlib
import hmac
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ValidationError
from pymongo.errors import DuplicateKeyError

SERVICIO = "payments"
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
ORDERS_URL = os.getenv("ORDERS_URL", "http://127.0.0.1:9002")

SECRETOS = {}
db = None


async def leer_secretos_vault():
    if not VAULT_TOKEN:
        raise RuntimeError("VAULT_TOKEN no está configurado")
    url = f"{VAULT_ADDR}/v1/secret/data/parrillada/{SERVICIO}"
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
    global db
    SECRETOS.update(await leer_secretos_vault())
    cliente_mongo = AsyncIOMotorClient(MONGO_URI)
    db = cliente_mongo["payments_db"]
    await db.pagos.create_index("payment_id", unique=True)
    await db.pagos.create_index("order_id")
    await db.eventos.create_index("event_id", unique=True)
    yield
    cliente_mongo.close()


app = FastAPI(title="payments - La Tienda del Fuego", lifespan=lifespan)


def verificar_llamador(*permitidos):
    def dependencia(x_service_name: str = Header(default=""), x_service_secret: str = Header(default="")):
        esperado = SECRETOS.get(f"entrada_{x_service_name}")
        if (x_service_name not in permitidos or esperado is None
                or not secrets.compare_digest(x_service_secret.encode(), esperado.encode())):
            raise HTTPException(status_code=403, detail="Solicitud no autorizada")
        return x_service_name
    return dependencia


def usuario_actual(x_user_id: str = Header(default=""), x_user_roles: str = Header(default="")):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Sesión requerida")
    return {"user_id": x_user_id, "roles": [r for r in x_user_roles.split(",") if r]}


async def llamar_orders(metodo: str, ruta: str, correlation_id: str, json=None):
    cabeceras = {
        "X-Service-Name": SERVICIO,
        "X-Service-Secret": SECRETOS["salida_orders"],
        "X-Correlation-Id": correlation_id,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as cliente:
            return await cliente.request(metodo, f"{ORDERS_URL}{ruta}", headers=cabeceras, json=json)
    except httpx.RequestError:
        return None


class PagoIn(BaseModel):
    # Solo se recibe el pedido. Si el navegador manda "monto", se ignora.
    order_id: str = Field(..., min_length=1, max_length=64)


class EventoProveedor(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=64)
    payment_id: str = Field(..., min_length=1, max_length=64)
    estado: Literal["aprobado", "rechazado"]
    monto: int = Field(..., gt=0)


def pago_publico(doc):
    return {
        "payment_id": doc["payment_id"],
        "order_id": doc["order_id"],
        "monto": doc["monto"],
        "estado": doc["estado"],
        "url_pago": f"https://sandbox.proveedor.test/pagar/{doc['payment_id']}",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICIO}


@app.post("/pagos", status_code=201)
async def iniciar_pago(datos: PagoIn, llamador: str = Depends(verificar_llamador("gateway")),
                       usuario: dict = Depends(usuario_actual), x_correlation_id: str = Header(default="")):
    respuesta = await llamar_orders("GET", f"/orders/{datos.order_id}", x_correlation_id)
    if respuesta is None:
        raise HTTPException(status_code=503, detail="No fue posible consultar el pedido")
    if respuesta.status_code == 404:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if respuesta.status_code != 200:
        raise HTTPException(status_code=502, detail="Respuesta inválida del servicio de pedidos")
    pedido = respuesta.json()

    # Propiedad: un cliente solo paga sus pedidos. Se responde 404 para no revelar pedidos ajenos.
    if pedido["user_id"] != usuario["user_id"]:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if pedido["estado"] != "pendiente":
        raise HTTPException(status_code=409, detail=f"El pedido está {pedido['estado']} y no se puede pagar")

    # Idempotencia del inicio: si ya hay un pago abierto para el pedido, se devuelve el mismo.
    existente = await db.pagos.find_one({"order_id": datos.order_id, "estado": {"$in": ["pendiente", "aprobado"]}})
    if existente:
        return pago_publico(existente)

    pago = {
        "payment_id": str(uuid.uuid4()),
        "order_id": datos.order_id,
        "user_id": usuario["user_id"],
        "monto": int(pedido["total"]),  # el total lo calculó orders en el servidor
        "estado": "pendiente",
        "notificado_orders": False,
        "creado": datetime.now(timezone.utc),
    }
    await db.pagos.insert_one(pago)
    return pago_publico(pago)


@app.get("/pagos/{payment_id}")
async def obtener_pago(payment_id: str, llamador: str = Depends(verificar_llamador("gateway")),
                       usuario: dict = Depends(usuario_actual)):
    doc = await db.pagos.find_one({"payment_id": payment_id})
    if doc is None or (doc["user_id"] != usuario["user_id"] and "operador" not in usuario["roles"]):
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    return pago_publico(doc)


@app.post("/pagos/webhook", dependencies=[Depends(verificar_llamador("gateway"))])
async def webhook_proveedor(request: Request, x_firma: str = Header(default=""),
                            x_correlation_id: str = Header(default="")):
    cuerpo = await request.body()

    # 1. Firma: HMAC-SHA256 del cuerpo exacto con la clave compartida con el proveedor.
    esperada = hmac.new(SECRETOS["clave_webhook"].encode(), cuerpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(x_firma, esperada):
        raise HTTPException(status_code=401, detail="Firma inválida")

    try:
        evento = EventoProveedor.model_validate_json(cuerpo)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Evento con formato inválido")

    pago = await db.pagos.find_one({"payment_id": evento.payment_id})
    if pago is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if evento.monto != pago["monto"]:
        raise HTTPException(status_code=422, detail="El monto no coincide con el pago")

    # 2. Idempotencia: el índice único hace que un evento repetido no se procese dos veces.
    try:
        await db.eventos.insert_one({
            "event_id": evento.event_id,
            "payment_id": evento.payment_id,
            "estado": evento.estado,
            "recibido": datetime.now(timezone.utc),
        })
    except DuplicateKeyError:
        return {"resultado": "duplicado", "estado": pago["estado"]}

    if pago["estado"] != "pendiente":
        return {"resultado": "sin_cambios", "estado": pago["estado"]}

    # 3. Cambio de estado del pago (solo desde pendiente).
    await db.pagos.update_one({"payment_id": pago["payment_id"]},
                              {"$set": {"estado": evento.estado, "actualizado": datetime.now(timezone.utc)}})

    # 4. Aviso a orders: pagado si se aprobó, anulado (libera stock) si se rechazó.
    nuevo_estado_pedido = "pagado" if evento.estado == "aprobado" else "anulado"
    respuesta = await llamar_orders("PATCH", f"/orders/{pago['order_id']}/estado", x_correlation_id,
                                    json={"estado": nuevo_estado_pedido, "motivo": f"pago {evento.estado}"})
    notificado = respuesta is not None and respuesta.status_code == 200
    await db.pagos.update_one({"payment_id": pago["payment_id"]}, {"$set": {"notificado_orders": notificado}})

    return {"resultado": "procesado", "estado": evento.estado, "pedido_notificado": notificado}


@app.post("/pagos/{payment_id}/reintentar-aviso")
async def reintentar_aviso(payment_id: str, llamador: str = Depends(verificar_llamador("gateway")),
                           usuario: dict = Depends(usuario_actual), x_correlation_id: str = Header(default="")):
    # Si orders estaba caído cuando llegó el webhook, el operador reintenta el aviso.
    if "operador" not in usuario["roles"]:
        raise HTTPException(status_code=403, detail="Requiere rol operador")
    pago = await db.pagos.find_one({"payment_id": payment_id})
    if pago is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pago["estado"] == "pendiente" or pago["notificado_orders"]:
        return {"resultado": "sin_cambios"}
    nuevo_estado_pedido = "pagado" if pago["estado"] == "aprobado" else "anulado"
    respuesta = await llamar_orders("PATCH", f"/orders/{pago['order_id']}/estado", x_correlation_id,
                                    json={"estado": nuevo_estado_pedido, "motivo": f"pago {pago['estado']}"})
    notificado = respuesta is not None and respuesta.status_code == 200
    await db.pagos.update_one({"payment_id": payment_id}, {"$set": {"notificado_orders": notificado}})
    return {"resultado": "reintentado", "pedido_notificado": notificado}

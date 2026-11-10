"""
orders (puerto 9002, red privada).
Crea pedidos y controla su ciclo de vida. Es la ÚNICA autoridad sobre el estado del pedido.

- El navegador envía solo producto_id y cantidad: precios y total los calcula el servidor
  con los datos que devuelve inventory al reservar.
- Estados: pendiente -> pagado -> en_despacho -> entregado, y anulado (sin borrar el registro).
- Un cliente solo ve y anula sus pedidos (si no es suyo, 404).
- Solo payments puede marcar "pagado"; solo el operador mueve a despacho/entregado.
- Al anular se libera el stock reservado.
"""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional

import httpx
from bson import ObjectId
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

SERVICIO = "orders"
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://127.0.0.1:9001")

TRANSICIONES = {
    "pendiente": {"pagado", "anulado"},
    "pagado": {"en_despacho"},
    "en_despacho": {"entregado"},
    "entregado": set(),
    "anulado": set(),
}
# Quién puede pedir cada estado destino.
PERMISO_ESTADO = {
    "pagado": {"payments"},
    "en_despacho": {"operador"},
    "entregado": {"operador"},
    "anulado": {"payments", "operador"},
}
ESTADOS_CON_VENTA = ["pagado", "en_despacho", "entregado"]

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
    db = cliente_mongo["orders_db"]
    await db.pedidos.create_index([("user_id", 1), ("creado", -1)])
    await db.pedidos.create_index([("user_id", 1), ("idempotency_key", 1)], unique=True,
                                  partialFilterExpression={"idempotency_key": {"$type": "string"}})
    yield
    cliente_mongo.close()


app = FastAPI(title="orders - La Tienda del Fuego", lifespan=lifespan)


def verificar_llamador(*permitidos):
    def dependencia(x_service_name: str = Header(default=""), x_service_secret: str = Header(default="")):
        esperado = SECRETOS.get(f"entrada_{x_service_name}")
        if (x_service_name not in permitidos or esperado is None
                or not secrets.compare_digest(x_service_secret.encode(), esperado.encode())):
            raise HTTPException(status_code=403, detail="Solicitud no autorizada")
        return x_service_name
    return dependencia


def usuario_opcional(x_user_id: str = Header(default=""), x_user_roles: str = Header(default="")):
    return {"user_id": x_user_id, "roles": [r for r in x_user_roles.split(",") if r]}


async def llamar_inventory(metodo: str, ruta: str, correlation_id: str, json=None):
    cabeceras = {"X-Service-Name": SERVICIO, "X-Service-Secret": SECRETOS["salida_inventory"],
                 "X-Correlation-Id": correlation_id}
    try:
        async with httpx.AsyncClient(timeout=5.0) as cliente:
            return await cliente.request(metodo, f"{INVENTORY_URL}{ruta}", headers=cabeceras, json=json)
    except httpx.RequestError:
        return None


class ItemIn(BaseModel):
    producto_id: str = Field(..., min_length=1, max_length=20)
    cantidad: int = Field(..., ge=1, le=20)


class PedidoIn(BaseModel):
    # Mismos datos que el formulario del frontend (producto, dirección, fecha de entrega).
    items: List[ItemIn] = Field(..., min_length=1, max_length=10)
    direccion_entrega: str = Field(..., min_length=5, max_length=120)
    fecha_entrega: date


class CambioEstadoIn(BaseModel):
    estado: Literal["pagado", "en_despacho", "entregado", "anulado"]
    motivo: Optional[str] = Field(None, max_length=120)


def pedido_salida(doc):
    return {
        "id": str(doc["_id"]),
        "user_id": doc["user_id"],
        "items": doc["items"],
        "total": doc["total"],
        "direccion_entrega": doc["direccion_entrega"],
        "fecha_entrega": doc["fecha_entrega"],
        "estado": doc["estado"],
        "historial": doc["historial"],
        "creado": doc["creado"].isoformat(),
    }


async def buscar_pedido(pedido_id: str):
    if not ObjectId.is_valid(pedido_id):
        return None
    return await db.pedidos.find_one({"_id": ObjectId(pedido_id)})


async def cambiar_estado(doc, nuevo: str, actor: str, motivo: Optional[str], correlation_id: str):
    actual = doc["estado"]
    if nuevo not in TRANSICIONES[actual]:
        raise HTTPException(status_code=409, detail=f"Transición no permitida: {actual} -> {nuevo}")
    evento = {"estado": nuevo, "fecha": datetime.now(timezone.utc).isoformat(), "por": actor, "motivo": motivo}
    # La condición "estado: actual" evita que dos cambios simultáneos se pisen.
    actualizado = await db.pedidos.find_one_and_update(
        {"_id": doc["_id"], "estado": actual},
        {"$set": {"estado": nuevo}, "$push": {"historial": evento}},
        return_document=ReturnDocument.AFTER,
    )
    if actualizado is None:
        raise HTTPException(status_code=409, detail="El pedido cambió de estado, vuelva a consultarlo")
    if nuevo == "anulado":
        await llamar_inventory("POST", f"/reservas/{doc['_id']}/liberar", correlation_id)
    return actualizado


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICIO}


@app.post("/orders", status_code=201)
async def crear_pedido(datos: PedidoIn, llamador: str = Depends(verificar_llamador("gateway")),
                       usuario: dict = Depends(usuario_opcional),
                       idempotency_key: Optional[str] = Header(default=None, max_length=64),
                       x_correlation_id: str = Header(default="")):
    if not usuario["user_id"] or "cliente" not in usuario["roles"]:
        raise HTTPException(status_code=403, detail="Solo un cliente puede crear pedidos")
    hoy = date.today()
    if datos.fecha_entrega < hoy or datos.fecha_entrega > hoy + timedelta(days=60):
        raise HTTPException(status_code=422, detail="La fecha de entrega debe estar entre hoy y 60 días más")

    # Reintento del mismo pedido (misma Idempotency-Key): se devuelve el ya creado.
    if idempotency_key:
        previo = await db.pedidos.find_one({"user_id": usuario["user_id"], "idempotency_key": idempotency_key})
        if previo:
            return pedido_salida(previo)

    pedido_id = ObjectId()
    reserva = {"pedido_id": str(pedido_id), "items": [i.model_dump() for i in datos.items]}
    respuesta = await llamar_inventory("POST", "/reservas", x_correlation_id, json=reserva)
    if respuesta is None:
        raise HTTPException(status_code=503, detail="Inventario no disponible, el pedido no se creó")
    if respuesta.status_code == 409:
        raise HTTPException(status_code=409, detail=respuesta.json().get("detail", "Stock insuficiente"))
    if respuesta.status_code != 201:
        raise HTTPException(status_code=502, detail="Respuesta inválida de inventario")

    items = []
    for item in respuesta.json()["items"]:
        item["subtotal"] = item["precio_unitario"] * item["cantidad"]
        items.append(item)
    ahora = datetime.now(timezone.utc)
    doc = {
        "_id": pedido_id,
        "user_id": usuario["user_id"],
        "items": items,
        "total": sum(i["subtotal"] for i in items),
        "direccion_entrega": datos.direccion_entrega,
        "fecha_entrega": datos.fecha_entrega.isoformat(),
        "estado": "pendiente",
        "historial": [{"estado": "pendiente", "fecha": ahora.isoformat(), "por": "cliente", "motivo": None}],
        "creado": ahora,
    }
    if idempotency_key:
        doc["idempotency_key"] = idempotency_key
    try:
        await db.pedidos.insert_one(doc)
    except Exception:
        # Si no se pudo guardar el pedido, se devuelve el stock reservado.
        await llamar_inventory("POST", f"/reservas/{pedido_id}/liberar", x_correlation_id)
        raise HTTPException(status_code=500, detail="No fue posible guardar el pedido")
    return pedido_salida(doc)


@app.get("/orders")
async def listar_pedidos(llamador: str = Depends(verificar_llamador("gateway", "graphql")),
                         usuario: dict = Depends(usuario_opcional),
                         estado: Optional[str] = Query(None),
                         solo_propios: bool = Query(False),
                         skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50)):
    filtro = {}
    if solo_propios or "operador" not in usuario["roles"]:
        if not usuario["user_id"]:
            raise HTTPException(status_code=401, detail="Sesión requerida")
        filtro["user_id"] = usuario["user_id"]  # un cliente solo ve lo suyo
    if estado:
        if estado not in TRANSICIONES:
            raise HTTPException(status_code=400, detail="Estado no válido")
        filtro["estado"] = estado
    total = await db.pedidos.count_documents(filtro)
    items = []
    async for doc in db.pedidos.find(filtro).sort("creado", -1).skip(skip).limit(limit):
        items.append(pedido_salida(doc))
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@app.get("/orders/analitica")
async def analitica(llamador: str = Depends(verificar_llamador("graphql")),
                    usuario: dict = Depends(usuario_opcional),
                    dias: int = Query(30, ge=1, le=365)):
    # Reporte pequeño (ventas por día y top de productos). Solo operador, solo montos agregados.
    if "operador" not in usuario["roles"]:
        raise HTTPException(status_code=403, detail="Requiere rol operador")
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    base = {"estado": {"$in": ESTADOS_CON_VENTA}, "creado": {"$gte": desde}}
    por_dia = []
    async for fila in db.pedidos.aggregate([
        {"$match": base},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$creado"}},
                    "pedidos": {"$sum": 1}, "monto": {"$sum": "$total"}}},
        {"$sort": {"_id": 1}},
    ]):
        por_dia.append({"fecha": fila["_id"], "pedidos": fila["pedidos"], "monto": fila["monto"]})
    top = []
    async for fila in db.pedidos.aggregate([
        {"$match": base},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.producto_id", "unidades": {"$sum": "$items.cantidad"},
                    "monto": {"$sum": "$items.subtotal"}}},
        {"$sort": {"unidades": -1}},
        {"$limit": 5},
    ]):
        top.append({"producto_id": fila["_id"], "unidades": fila["unidades"], "monto": fila["monto"]})
    return {"dias": dias, "ventas_por_dia": por_dia, "top_productos": top}


@app.get("/orders/{pedido_id}")
async def obtener_pedido(pedido_id: str, llamador: str = Depends(verificar_llamador("gateway", "graphql", "payments")),
                         usuario: dict = Depends(usuario_opcional)):
    doc = await buscar_pedido(pedido_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if llamador == "payments":
        return pedido_salida(doc)  # payments verifica la propiedad con el user_id que recibe
    if "operador" not in usuario["roles"] and doc["user_id"] != usuario["user_id"]:
        # 404 y no 403: no se revela que el pedido existe.
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return pedido_salida(doc)


@app.post("/orders/{pedido_id}/anular")
async def anular_pedido(pedido_id: str, llamador: str = Depends(verificar_llamador("gateway")),
                        usuario: dict = Depends(usuario_opcional), x_correlation_id: str = Header(default="")):
    doc = await buscar_pedido(pedido_id)
    es_operador = "operador" in usuario["roles"]
    if doc is None or (not es_operador and doc["user_id"] != usuario["user_id"]):
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    actor = "operador" if es_operador else "cliente"
    actualizado = await cambiar_estado(doc, "anulado", actor, "anulado por " + actor, x_correlation_id)
    return pedido_salida(actualizado)


@app.patch("/orders/{pedido_id}/estado")
async def cambiar_estado_pedido(pedido_id: str, datos: CambioEstadoIn,
                                llamador: str = Depends(verificar_llamador("gateway", "payments")),
                                usuario: dict = Depends(usuario_opcional),
                                x_correlation_id: str = Header(default="")):
    actor = "payments" if llamador == "payments" else ("operador" if "operador" in usuario["roles"] else "")
    if actor not in PERMISO_ESTADO[datos.estado]:
        raise HTTPException(status_code=403, detail="No tiene permiso para ese cambio de estado")
    doc = await buscar_pedido(pedido_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    actualizado = await cambiar_estado(doc, datos.estado, actor, datos.motivo, x_correlation_id)
    return pedido_salida(actualizado)

"""
inventory (puerto 9001, red privada). Basado en fastapi/main.py de clases.
Catálogo público, stock y reservas atómicas. Es la ÚNICA autoridad sobre el stock.

- El catálogo devuelve solo campos públicos; el número de stock solo lo ve el operador.
- Reservar descuenta stock con find_one_and_update + condición stock >= cantidad:
  la operación es atómica en Mongo, así dos pedidos simultáneos no pueden dejar stock negativo.
- Una reserva por pedido (idempotente): reintentar no descuenta dos veces.
- Los productos no se borran (se desactivan) para conservar el historial de pedidos.
"""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

SERVICIO = "inventory"
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
LINEAS = ["Parrilla Directa", "Smoked & Ready", "Cajas Parrilleras"]

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
    db = cliente_mongo["inventory_db"]
    await db.reservas.create_index("pedido_id", unique=True)
    yield
    cliente_mongo.close()


app = FastAPI(title="inventory - La Tienda del Fuego", lifespan=lifespan)


def verificar_llamador(*permitidos):
    def dependencia(x_service_name: str = Header(default=""), x_service_secret: str = Header(default="")):
        esperado = SECRETOS.get(f"entrada_{x_service_name}")
        if (x_service_name not in permitidos or esperado is None
                or not secrets.compare_digest(x_service_secret.encode(), esperado.encode())):
            raise HTTPException(status_code=403, detail="Solicitud no autorizada")
        return x_service_name
    return dependencia


def exigir_operador(x_user_roles: str = Header(default="")):
    # Defensa en profundidad: el gateway ya revisó el rol, el servicio lo vuelve a revisar.
    if "operador" not in x_user_roles.split(","):
        raise HTTPException(status_code=403, detail="Requiere rol operador")


class ProductoIn(BaseModel):
    id: str = Field(..., pattern=r"^[A-Z]{4}-\d{2}$", description="Código, ej: PARR-01")
    nombre: str = Field(..., min_length=3, max_length=80)
    linea: str = Field(..., min_length=3, max_length=40)
    formato: str = Field(..., min_length=1, max_length=40)
    descripcion: str = Field(..., min_length=5, max_length=300)
    precio: int = Field(..., gt=0, le=10_000_000, description="CLP, sin decimales")
    stock: int = Field(..., ge=0, le=100_000)
    activo: bool = True


class ProductoCambios(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=80)
    linea: str = Field(..., min_length=3, max_length=40)
    formato: str = Field(..., min_length=1, max_length=40)
    descripcion: str = Field(..., min_length=5, max_length=300)
    precio: int = Field(..., gt=0, le=10_000_000)
    activo: bool = True


class StockIn(BaseModel):
    stock: int = Field(..., ge=0, le=100_000)


class ItemReserva(BaseModel):
    producto_id: str = Field(..., min_length=1, max_length=20)
    cantidad: int = Field(..., ge=1, le=50)


class ReservaIn(BaseModel):
    pedido_id: str = Field(..., min_length=1, max_length=64)
    items: List[ItemReserva] = Field(..., min_length=1, max_length=20)


def producto_publico(doc, ver_stock=False):
    salida = {
        "id": doc["_id"],
        "nombre": doc["nombre"],
        "linea": doc["linea"],
        "formato": doc["formato"],
        "descripcion": doc["descripcion"],
        "precio": doc["precio"],
        "disponible": doc["activo"] and doc["stock"] > 0,
    }
    if ver_stock:
        salida["stock"] = doc["stock"]
        salida["activo"] = doc["activo"]
    return salida


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICIO}


@app.get("/productos")
async def listar_productos(llamador: str = Depends(verificar_llamador("gateway", "graphql", "orders")),
                           x_user_roles: str = Header(default=""),
                           linea: Optional[str] = Query(None, max_length=40),
                           disponible: Optional[bool] = Query(None),
                           ids: Optional[str] = Query(None, max_length=500, description="Lote: PARR-01,SMOK-02"),
                           skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    filtro = {}
    if ids:
        # Consulta en lote: GraphQL y orders piden varios productos en UNA llamada (evita N+1).
        filtro["_id"] = {"$in": [i.strip() for i in ids.split(",") if i.strip()][:100]}
    else:
        filtro["activo"] = True
    if linea:
        if linea not in LINEAS:
            raise HTTPException(status_code=400, detail="Línea no válida")
        filtro["linea"] = linea
    if disponible is True:
        filtro["stock"] = {"$gt": 0}
    elif disponible is False:
        filtro["stock"] = 0
    ver_stock = "operador" in x_user_roles.split(",")
    items = []
    async for doc in db.productos.find(filtro).sort("_id", 1).skip(skip).limit(limit):
        items.append(producto_publico(doc, ver_stock))
    return items


@app.get("/productos/{producto_id}")
async def obtener_producto(producto_id: str,
                           llamador: str = Depends(verificar_llamador("gateway", "graphql", "orders")),
                           x_user_roles: str = Header(default="")):
    doc = await db.productos.find_one({"_id": producto_id})
    ver_stock = "operador" in x_user_roles.split(",")
    if doc is None or (not doc["activo"] and not ver_stock):
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto_publico(doc, ver_stock)


@app.post("/productos", status_code=201,
          dependencies=[Depends(verificar_llamador("gateway")), Depends(exigir_operador)])
async def crear_producto(datos: ProductoIn):
    if datos.linea not in LINEAS:
        raise HTTPException(status_code=400, detail="Línea no válida")
    doc = datos.model_dump()
    doc["_id"] = doc.pop("id")
    doc["creado"] = datetime.now(timezone.utc)
    try:
        await db.productos.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Ya existe un producto con ese código")
    return producto_publico(doc, True)


@app.put("/productos/{producto_id}",
         dependencies=[Depends(verificar_llamador("gateway")), Depends(exigir_operador)])
async def actualizar_producto(producto_id: str, datos: ProductoCambios):
    if datos.linea not in LINEAS:
        raise HTTPException(status_code=400, detail="Línea no válida")
    cambios = datos.model_dump()
    cambios["actualizado"] = datetime.now(timezone.utc)
    doc = await db.productos.find_one_and_update({"_id": producto_id}, {"$set": cambios},
                                                 return_document=ReturnDocument.AFTER)
    if doc is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto_publico(doc, True)


@app.patch("/productos/{producto_id}/stock",
           dependencies=[Depends(verificar_llamador("gateway")), Depends(exigir_operador)])
async def fijar_stock(producto_id: str, datos: StockIn):
    doc = await db.productos.find_one_and_update({"_id": producto_id}, {"$set": {"stock": datos.stock}},
                                                 return_document=ReturnDocument.AFTER)
    if doc is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto_publico(doc, True)


@app.post("/reservas", status_code=201, dependencies=[Depends(verificar_llamador("orders"))])
async def reservar(datos: ReservaIn):
    # Idempotencia: si orders reintenta la misma reserva, se devuelve la existente.
    existente = await db.reservas.find_one({"pedido_id": datos.pedido_id})
    if existente:
        return {"pedido_id": existente["pedido_id"], "items": existente["items"], "estado": existente["estado"]}

    # Agrupar cantidades del mismo producto.
    cantidades = {}
    for item in datos.items:
        cantidades[item.producto_id] = cantidades.get(item.producto_id, 0) + item.cantidad

    reservados = []
    for producto_id, cantidad in cantidades.items():
        doc = await db.productos.find_one_and_update(
            {"_id": producto_id, "activo": True, "stock": {"$gte": cantidad}},
            {"$inc": {"stock": -cantidad}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            # Sin stock (o no existe): se devuelve lo ya descontado y se rechaza todo el pedido.
            for previo in reservados:
                await db.productos.update_one({"_id": previo["producto_id"]}, {"$inc": {"stock": previo["cantidad"]}})
            raise HTTPException(status_code=409, detail=f"Stock insuficiente para {producto_id}")
        # Precio y nombre los fija el servidor en el momento de reservar.
        reservados.append({"producto_id": producto_id, "nombre": doc["nombre"],
                           "cantidad": cantidad, "precio_unitario": doc["precio"]})

    await db.reservas.insert_one({"pedido_id": datos.pedido_id, "items": reservados, "estado": "activa",
                                  "creado": datetime.now(timezone.utc)})
    return {"pedido_id": datos.pedido_id, "items": reservados, "estado": "activa"}


@app.post("/reservas/{pedido_id}/liberar", dependencies=[Depends(verificar_llamador("orders"))])
async def liberar(pedido_id: str):
    # Solo libera una vez: el cambio activa -> liberada es atómico.
    reserva = await db.reservas.find_one_and_update({"pedido_id": pedido_id, "estado": "activa"},
                                                    {"$set": {"estado": "liberada"}})
    if reserva is None:
        return {"pedido_id": pedido_id, "resultado": "sin_cambios"}
    for item in reserva["items"]:
        await db.productos.update_one({"_id": item["producto_id"]}, {"$inc": {"stock": item["cantidad"]}})
    return {"pedido_id": pedido_id, "resultado": "liberada"}

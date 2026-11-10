"""
clients (puerto 9004, red privada).
Perfiles de clientes: nombre, correo y dirección de entrega (los mismos datos del formulario del frontend).
Son datos personales RESTRINGIDOS: cada cliente solo ve y edita su propio perfil.
"""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

SERVICIO = "clients"
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
PATRON_CORREO = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

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
    db = cliente_mongo["clients_db"]
    await db.clientes.create_index("user_id", unique=True)
    yield
    cliente_mongo.close()


app = FastAPI(title="clients - La Tienda del Fuego", lifespan=lifespan)


def verificar_llamador(*permitidos):
    def dependencia(x_service_name: str = Header(default=""), x_service_secret: str = Header(default="")):
        esperado = SECRETOS.get(f"entrada_{x_service_name}")
        if (x_service_name not in permitidos or esperado is None
                or not secrets.compare_digest(x_service_secret.encode(), esperado.encode())):
            raise HTTPException(status_code=403, detail="Solicitud no autorizada")
        return x_service_name
    return dependencia


def usuario_actual(x_user_id: str = Header(default=""), x_user_roles: str = Header(default="")):
    # Estas cabeceras solo se confían porque antes se verificó que la llamada viene del gateway,
    # y el gateway las arma desde la introspección (descarta las que manda el navegador).
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Sesión requerida")
    return {"user_id": x_user_id, "roles": [r for r in x_user_roles.split(",") if r]}


class PerfilNuevo(BaseModel):
    user_id: str = Field(..., min_length=1)
    nombre: str = Field(..., min_length=3, max_length=80)
    correo: str = Field(..., max_length=120, pattern=PATRON_CORREO)
    direccion: str = Field(..., min_length=5, max_length=120)


class PerfilCambios(BaseModel):
    # El correo no se cambia aquí: es la identidad de login y la administra auth.
    nombre: str = Field(..., min_length=3, max_length=80)
    direccion: str = Field(..., min_length=5, max_length=120)


def perfil_completo(doc):
    return {"user_id": doc["user_id"], "nombre": doc["nombre"], "correo": doc["correo"], "direccion": doc["direccion"]}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICIO}


@app.post("/clientes", status_code=201, dependencies=[Depends(verificar_llamador("auth"))])
async def crear_perfil(datos: PerfilNuevo):
    # Solo auth puede crear perfiles (al registrar un usuario).
    doc = datos.model_dump()
    doc["creado"] = datetime.now(timezone.utc)
    try:
        await db.clientes.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="El perfil ya existe")
    return perfil_completo(doc)


@app.get("/clientes/me")
async def mi_perfil(llamador: str = Depends(verificar_llamador("gateway")), usuario: dict = Depends(usuario_actual)):
    doc = await db.clientes.find_one({"user_id": usuario["user_id"]})
    if doc is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return perfil_completo(doc)


@app.put("/clientes/me")
async def actualizar_mi_perfil(datos: PerfilCambios, llamador: str = Depends(verificar_llamador("gateway")),
                               usuario: dict = Depends(usuario_actual)):
    cambios = datos.model_dump()
    cambios["actualizado"] = datetime.now(timezone.utc)
    resultado = await db.clientes.update_one({"user_id": usuario["user_id"]}, {"$set": cambios})
    if resultado.matched_count == 0:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    doc = await db.clientes.find_one({"user_id": usuario["user_id"]})
    return perfil_completo(doc)


@app.get("/clientes")
async def listar_clientes(llamador: str = Depends(verificar_llamador("gateway")),
                          usuario: dict = Depends(usuario_actual),
                          skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    if "operador" not in usuario["roles"]:
        raise HTTPException(status_code=403, detail="Requiere rol operador")
    # El listado no incluye la dirección: para gestionar la tienda basta con nombre y correo.
    items = []
    async for doc in db.clientes.find({}).skip(skip).limit(limit):
        items.append({"user_id": doc["user_id"], "nombre": doc["nombre"], "correo": doc["correo"]})
    return {"items": items, "skip": skip, "limit": limit}


@app.get("/clientes/{user_id}")
async def obtener_cliente(user_id: str, llamador: str = Depends(verificar_llamador("gateway", "graphql")),
                          x_user_roles: str = Header(default="")):
    doc = await db.clientes.find_one({"user_id": user_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if llamador == "graphql":
        # La agregación solo necesita el nombre para mostrar el pedido.
        return {"user_id": doc["user_id"], "nombre": doc["nombre"]}
    if "operador" not in x_user_roles.split(","):
        raise HTTPException(status_code=403, detail="Requiere rol operador")
    return perfil_completo(doc)

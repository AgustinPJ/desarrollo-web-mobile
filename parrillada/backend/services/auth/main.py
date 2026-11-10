"""
Auth Service (puerto 8100, red privada).
Registro, login, introspección y logout. Guarda identidades y sesiones en auth_db.
Basado en el auth-service que vimos en clases, con persistencia en Mongo, bcrypt y sesiones con expiración.
"""
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

SERVICIO = "auth"
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
CLIENTS_URL = os.getenv("CLIENTS_URL", "http://127.0.0.1:9004")
MINUTOS_SESION = 30
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
    db = cliente_mongo["auth_db"]
    await db.usuarios.create_index("email", unique=True)
    await db.sesiones.create_index("token_hash", unique=True)
    # Índice TTL: Mongo borra solo las sesiones vencidas (retención mínima de datos).
    await db.sesiones.create_index("expira", expireAfterSeconds=0)
    yield
    cliente_mongo.close()


app = FastAPI(title="Auth Service - La Tienda del Fuego", lifespan=lifespan)


def verificar_llamador(*permitidos):
    """Acepta solo a los servicios permitidos que envían su secreto de tramo correcto."""
    def dependencia(x_service_name: str = Header(default=""), x_service_secret: str = Header(default="")):
        esperado = SECRETOS.get(f"entrada_{x_service_name}")
        if (x_service_name not in permitidos or esperado is None
                or not secrets.compare_digest(x_service_secret.encode(), esperado.encode())):
            raise HTTPException(status_code=403, detail="Solicitud no autorizada")
        return x_service_name
    return dependencia


def hash_token(token: str) -> str:
    # En la BD se guarda el SHA-256 del token, no el token: si se filtra la BD, las sesiones no sirven.
    return hashlib.sha256(token.encode()).hexdigest()


class RegistroIn(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=80)
    correo: str = Field(..., max_length=120, pattern=PATRON_CORREO)
    direccion: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=8, max_length=72)


class LoginIn(BaseModel):
    correo: str = Field(..., max_length=120, pattern=PATRON_CORREO)
    password: str = Field(..., min_length=1, max_length=72)


class TokenIn(BaseModel):
    token: str


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICIO}


@app.post("/registro", status_code=201, dependencies=[Depends(verificar_llamador("gateway"))])
async def registro(datos: RegistroIn, x_correlation_id: str = Header(default="")):
    correo = datos.correo.lower()
    password_hash = bcrypt.hashpw(datos.password.encode(), bcrypt.gensalt()).decode()
    usuario = {
        "email": correo,
        "password_hash": password_hash,
        "roles": ["cliente"],  # el rol nunca lo elige quien se registra
        "creado": datetime.now(timezone.utc),
    }
    try:
        resultado = await db.usuarios.insert_one(usuario)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="El correo ya está registrado")
    user_id = str(resultado.inserted_id)

    # Crear el perfil en clients (datos personales viven allá, no aquí).
    perfil = {"user_id": user_id, "nombre": datos.nombre, "correo": correo, "direccion": datos.direccion}
    cabeceras = {
        "X-Service-Name": SERVICIO,
        "X-Service-Secret": SECRETOS["salida_clients"],
        "X-Correlation-Id": x_correlation_id,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as cliente:
            respuesta = await cliente.post(f"{CLIENTS_URL}/clientes", json=perfil, headers=cabeceras)
    except httpx.RequestError:
        respuesta = None
    if respuesta is None or respuesta.status_code != 201:
        # Compensación: si no se pudo crear el perfil, se deshace la identidad.
        await db.usuarios.delete_one({"_id": resultado.inserted_id})
        raise HTTPException(status_code=503, detail="No fue posible completar el registro, intente más tarde")

    return {"user_id": user_id, "correo": correo, "roles": usuario["roles"]}


@app.post("/login", dependencies=[Depends(verificar_llamador("gateway"))])
async def login(datos: LoginIn):
    usuario = await db.usuarios.find_one({"email": datos.correo.lower()})
    if usuario is None or not bcrypt.checkpw(datos.password.encode(), usuario["password_hash"].encode()):
        # Mismo mensaje para correo inexistente y clave mala.
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    token = secrets.token_urlsafe(32)
    expira = datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_SESION)
    await db.sesiones.insert_one({
        "token_hash": hash_token(token),
        "user_id": str(usuario["_id"]),
        "email": usuario["email"],
        "roles": usuario["roles"],
        "expira": expira,
        "revocada": False,
    })
    return {"access_token": token, "token_type": "bearer", "expires_in": MINUTOS_SESION * 60}


@app.post("/introspect", dependencies=[Depends(verificar_llamador("gateway"))])
async def introspect(datos: TokenIn):
    sesion = await db.sesiones.find_one({"token_hash": hash_token(datos.token)})
    if sesion is None or sesion["revocada"]:
        return {"active": False}
    expira = sesion["expira"].replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expira:
        return {"active": False}
    return {
        "active": True,
        "user_id": sesion["user_id"],
        "email": sesion["email"],
        "roles": sesion["roles"],
        "expires_at": expira.isoformat(),
    }


@app.post("/logout", dependencies=[Depends(verificar_llamador("gateway"))])
async def logout(datos: TokenIn):
    # Revocar: la sesión queda inválida aunque no haya vencido.
    await db.sesiones.update_one({"token_hash": hash_token(datos.token)}, {"$set": {"revocada": True}})
    return {"mensaje": "Sesión finalizada"}

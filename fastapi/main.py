from typing import List, Optional, Dict
from itertools import count

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field 

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from contextlib import asynccontextmanager

MONGODB_URL = "mongodb://localhost:27017"
DB_NAME = "bd_parrilladas"
COLL_NAME = "items"

client: AsyncIOMotorClient = AsyncIOMotorClient(MONGODB_URL)
DB = None
coll = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, DB, coll
    client = AsyncIOMotorClient(MONGODB_URL)
    DB = client[DB_NAME]
    coll = DB[COLL_NAME]
    yield
    client.close()

app = FastAPI(title="Parrilladas API", version = "1.0.0", lifespan=lifespan)

class Item(BaseModel):
    nombre : str = Field( min_length=1, description= "nombre del producto")
    precio : float = Field(gt=0, description= "precio del producto")
    tags : List[str] = Field(default_factory=list)
    activo: bool = True

class ItemIn(BaseModel):
    nombre: str = Field(min_length=1, description="nombre del producto")
    precio: float = Field(gt=0, description="precio del producto")
    tags: List[str] = Field(default_factory=list)
    activo: bool = True


class ItemOut(Item):
    id: str

def doc_to_itemout(doc) -> ItemOut:
    return ItemOut(
        id = str(doc["_id"]),
        nombre = doc["nombre"],
        precio = doc["precio"],
        tags = doc.get("tags", []),
        activo = doc.get("activo", True)
    )

#ENDpoints
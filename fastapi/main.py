from contextlib import asynccontextmanager
from typing import List, Optional
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

# 1. Configuración de MongoDB
MONGODB_URI = "mongodb://localhost:27017"
DB_NAME = "bd_parrilladas"  # Base de datos de la parrillada
COLL_NAME = "productos"    # Colección de cortes/platos

client: AsyncIOMotorClient | None = None
db = None
coll = None


# 2. Ciclo de vida asíncrono (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db, coll
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]
    coll = db[COLL_NAME]
    yield
    client.close()


# 3. Instancia de FastAPI
app = FastAPI(
    title="Parrilladas API - Backend REST",
    version="1.0.0",
    lifespan=lifespan
)


# 4. Modelos Pydantic (Validación de datos)
class ProductoIn(BaseModel):
    nombre: str = Field(..., min_length=2, description="Nombre del corte o plato")
    estilo: str = Field(..., min_length=2, description="Parrilla, Ahumado, etc.")
    descripcion: str = Field(..., min_length=5, description="Detalle del producto")
    precio: float = Field(..., gt=0, description="Precio en pesos chilenos")


class ProductoOut(ProductoIn):
    id: str


# 5. Función auxiliar para transformar el _id nativo de MongoDB a string
def doc_to_productoout(doc: dict) -> ProductoOut:
    return ProductoOut(
        id=str(doc["_id"]),
        nombre=doc.get("nombre", ""),
        estilo=doc.get("estilo", ""),
        descripcion=doc.get("descripcion", ""),
        precio=float(doc.get("precio", 0.0)),
    )


# 6. Endpoints / Rutas

@app.get("/health", tags=["sistema"])
def health():
    return {"status": "ok", "service": "Parrilladas Backend API"}


@app.get("/productos", response_model=List[ProductoOut], tags=["productos"])
async def listar_productos(
    q: Optional[str] = Query(None, description="Filtro por nombre que contenga q"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    query = {}
    if q:
        query["nombre"] = {"$regex": q, "$options": "i"}

    cursor = coll.find(query).skip(skip).limit(limit)
    items: List[ProductoOut] = []
    async for doc in cursor:
        items.append(doc_to_productoout(doc))
    return items


@app.post("/productos", response_model=ProductoOut, status_code=status.HTTP_201_CREATED, tags=["productos"])
async def crear_producto(item: ProductoIn):
    res = await coll.insert_one(item.model_dump())
    doc = await coll.find_one({"_id": res.inserted_id})
    return doc_to_productoout(doc)


@app.get("/productos/{producto_id}", response_model=ProductoOut, status_code=status.HTTP_200_OK, tags=["productos"])
async def obtener_producto(producto_id: str):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID con formato inválido")
    doc = await coll.find_one({"_id": ObjectId(producto_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return doc_to_productoout(doc)


@app.put("/productos/{producto_id}", response_model=ProductoOut, tags=["productos"])
async def actualizar_producto(producto_id: str, item: ProductoIn):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID con formato inválido")

    res = await coll.update_one(
        {"_id": ObjectId(producto_id)},
        {"$set": item.model_dump()}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    doc = await coll.find_one({"_id": ObjectId(producto_id)})
    return doc_to_productoout(doc)


@app.delete("/productos/{producto_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["productos"])
async def eliminar_producto(producto_id: str):
    if not ObjectId.is_valid(producto_id):
        raise HTTPException(status_code=400, detail="ID con formato inválido")

    res = await coll.delete_one({"_id": ObjectId(producto_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return None
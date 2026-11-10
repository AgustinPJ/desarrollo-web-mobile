"""
Datos de prueba ficticios, tomados del frontend (parrillada_frontend/data/productos.json).

- inventory_db.productos: los 7 productos del frontend. Stock 20 si estaban "disponible", 0 si no.
- auth_db / clients_db: un usuario operador (administrador de la tienda).
  Su contraseña se lee de la variable OPERADOR_PASSWORD (no queda escrita en el código).

Se puede ejecutar varias veces: actualiza en vez de duplicar.
Uso:
    $env:OPERADOR_PASSWORD="una-clave-de-prueba"
    python datos/cargar_datos.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
OPERADOR_CORREO = os.getenv("OPERADOR_CORREO", "operador@tiendadelfuego.cl")
OPERADOR_PASSWORD = os.getenv("OPERADOR_PASSWORD")
ARCHIVO_PRODUCTOS = Path(__file__).resolve().parent.parent.parent / "parrillada_frontend" / "data" / "productos.json"


def main():
    if not OPERADOR_PASSWORD or len(OPERADOR_PASSWORD) < 8:
        sys.exit("Defina OPERADOR_PASSWORD (mínimo 8 caracteres) antes de cargar los datos")

    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    ahora = datetime.now(timezone.utc)

    # 1. Productos del frontend -> inventory
    productos = json.loads(ARCHIVO_PRODUCTOS.read_text(encoding="utf-8"))["productos"]
    for p in productos:
        mongo.inventory_db.productos.update_one(
            {"_id": p["id"]},
            {"$set": {
                "nombre": p["nombre"], "linea": p["linea"], "formato": p["formato"],
                "descripcion": p["descripcion"], "precio": int(p["precio"]),
                "stock": 20 if p["disponible"] else 0, "activo": True,
            }, "$setOnInsert": {"creado": ahora}},
            upsert=True,
        )
    print(f"[ok] {len(productos)} productos cargados en inventory_db")

    # 2. Operador -> auth (identidad) y clients (perfil)
    password_hash = bcrypt.hashpw(OPERADOR_PASSWORD.encode(), bcrypt.gensalt()).decode()
    resultado = mongo.auth_db.usuarios.find_one_and_update(
        {"email": OPERADOR_CORREO},
        {"$set": {"password_hash": password_hash, "roles": ["operador"]}, "$setOnInsert": {"creado": ahora}},
        upsert=True, return_document=True,
    )
    user_id = str(resultado["_id"])
    mongo.clients_db.clientes.update_one(
        {"user_id": user_id},
        {"$set": {"nombre": "Operador Tienda", "correo": OPERADOR_CORREO, "direccion": "Bodega central 100"},
         "$setOnInsert": {"creado": ahora}},
        upsert=True,
    )
    print(f"[ok] operador {OPERADOR_CORREO} listo (la clave no se muestra)")


if __name__ == "__main__":
    main()

from fastapi import FastAPI

app = FastAPI(
    title="Backend API",
    description=" API ubicada en el localhost enrutada por API gateway /api/productos y /api/ordenes"
)

@app.get("/health")
def health():
    return {
        "status": "OK",
        "service": "Backend API"
    }

@app.get("/productos")
def products():
    return {
        "products": [
            {"id": 1, "nombre": "Producto 1", "precio": 10000},
            {"id": 2, "nombre": "Producto 2", "precio": 20000},
            {"id": 3, "nombre": "Producto 3", "precio": 30000}
        ]
    }

@app.get("/ordenes")
def orders():
    return {
        "orders": [
            {"id": 1, "producto_id": 1, "estado": "pagado"},
            {"id": 2, "producto_id": 2, "estado": "pendiente"},
            {"id": 3, "producto_id": 3, "estado": "cancelado"}
        ]
    }
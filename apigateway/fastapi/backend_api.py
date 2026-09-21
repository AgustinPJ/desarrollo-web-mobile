from fastapi import FastAPI

app = FastAPI(
    title="Backend API",
    description=" API ubicada en el localhost enrutada por API gateway /api/products y /api/orders"
)

@app.get("/health")
def health():
    return {
        "status": "OK",
        "service": "Backend API"
    }

@app.get("/products")
def products():
    return {
        "products": [
            {"id": 1, "name": "Product 1", "price": 10000},
            {"id": 2, "name": "Product 2", "price": 20000},
            {"id": 3, "name": "Product 3", "price": 30000}
        ]
    }

@app.get("/orders")
def orders():
    return {
        "orders": [
            {"id": 1, "product_id": 1, "status": "paid"},
            {"id": 2, "product_id": 2, "status": "pending"},
            {"id": 3, "product_id": 3, "status": "cancelled"}
        ]
    }
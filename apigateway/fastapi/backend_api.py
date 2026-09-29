import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Depends

app = FastAPI(
    title="Protected Backend API",
    description="API protegida: solo acepta solicitudes que vengan del API Gateway (/api/products y /api/orders)"
)

# Secreto compartido Gateway -> Backend (mismo valor que backend_shared_secret en Vault)
INTERNAL_GATEWAY_SECRET = os.getenv("INTERNAL_GATEWAY_SECRET")

if not INTERNAL_GATEWAY_SECRET:
    raise RuntimeError("INTERNAL_GATEWAY_SECRET no esta configurado")


def verify_gateway(x_gateway_secret: str = Header(default="")):
    # compare_digest evita ataques de timing; se comparan bytes para tolerar caracteres no ASCII
    valid = secrets.compare_digest(
        x_gateway_secret.encode("utf-8"),
        INTERNAL_GATEWAY_SECRET.encode("utf-8")
    )
    if not valid:
        raise HTTPException(
            status_code=403,
            detail="Solicitud no autorizada desde Gateway"
        )


@app.get("/health")
def health():
    return {
        "status": "OK",
        "service": "Backend API"
    }


@app.get("/products", dependencies=[Depends(verify_gateway)])
def products(x_authenticated_client: str | None = Header(default=None)):
    return {
        "authenticated_client": x_authenticated_client,
        "products": [
            {"id": 1, "name": "Product 1", "price": 10000},
            {"id": 2, "name": "Product 2", "price": 20000},
            {"id": 3, "name": "Product 3", "price": 30000}
        ]
    }


@app.get("/orders", dependencies=[Depends(verify_gateway)])
def orders(x_authenticated_client: str | None = Header(default=None)):
    return {
        "authenticated_client": x_authenticated_client,
        "orders": [
            {"id": 1, "product_id": 1, "status": "paid"},
            {"id": 2, "product_id": 2, "status": "pending"},
            {"id": 3, "product_id": 3, "status": "cancelled"}
        ]
    }

import os
import secrets
import httpx
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

app = FastAPI(
    title="Local API Gateway Seguro",
    description="API Gateway con autenticación Bearer y secretos administrados en HashiCorp Vault"
)


security = HTTPBearer(auto_error=False)

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:9000")
BACKEND_URL2 = os.getenv("BACKEND_URL2", "http://localhost:9100")

if not VAULT_TOKEN:
    raise RuntimeError("VAULT_TOKEN no configurado en variables de entorno")



async def get_gateway_secrets():
    url = f"{VAULT_ADDR}/v1/secret/data/gateway"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.get(url, headers=headers)
        except httpx.RequestError:
            raise HTTPException(status_code=500, detail="No fue posible conectar con Vault")
            
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="No fue posible acceder a los secretos en Vault")
        
    vault_response = response.json()
    return vault_response["data"]["data"]


async def authenticate_client(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token requerido")
        
    vault_secrets = await get_gateway_secrets()
    expected_token = vault_secrets["client_token"]
    received_token = credentials.credentials
    
    valid = secrets.compare_digest(received_token, expected_token)
    if not valid:
        raise HTTPException(status_code=401, detail="Token invalido")
        
    return {
        "client_id": "student-client",
        "backend_secret": vault_secrets["backend_shared_secret"]
    }


@app.get("/health", tags=["sistema"])
def health():
    return {"status": "OK", "service": "Local API Gateway"}



@app.get("/api/products")
async def products(auth: dict = Depends(authenticate_client)):
    headers = {
        "X-Gateway-Secret": auth["backend_secret"],
        "X-Authenticated-Client": auth["client_id"]
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BACKEND_URL}/products", headers=headers)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Backend no disponible")
        
    return response.json()


@app.get("/api/productos")
async def productos(auth: dict = Depends(authenticate_client)):
    headers = {
        "X-Gateway-Secret": auth["backend_secret"],
        "X-Authenticated-Client": auth["client_id"]
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BACKEND_URL2}/productos", headers=headers)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Backend 2 no disponible")
        
    return response.json()


@app.get("/api/orders")
async def orders(auth: dict = Depends(authenticate_client)):
    headers = {
        "X-Gateway-Secret": auth["backend_secret"],
        "X-Authenticated-Client": auth["client_id"]
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BACKEND_URL}/orders", headers=headers)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Backend no disponible")
        
    return response.json()
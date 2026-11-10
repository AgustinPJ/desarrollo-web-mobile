# La Tienda del Fuego · Backend seguro (Evaluación 2)

Backend de la tienda parrillera "La Tienda del Fuego" (Desarrollo Web y Mobile, UNAB).
Integrantes: Agustín Pacheco y David León. Frontend de referencia: `parrillada_frontend/` (versión Eval 1 rediseñada);
los datos de prueba salen de ese frontend (`parrillada_frontend/data/productos.json` y su formulario de pedido).

## Estructura

```text
parrillada/
├── README.md
├── parrillada_frontend/   Evaluación 1: frontend (Bootstrap 5 + JavaScript) y datos de prueba
├── backend/               Evaluación 2: backend seguro
│   ├── services/          gateway, auth, clients, inventory, orders, payments y graphql
│   ├── vault/             carga y rotación de secretos (cargar_secretos.py)
│   ├── datos/             carga de datos de prueba (cargar_datos.py)
│   ├── tests/             pruebas de seguridad, negocio, demo de flujos y carga
│   └── iniciar.ps1, detener.ps1, requirements.txt, .env.example
├── docs/                  informe, diagramas y evidencias
└── mensajeria/            PR semanal de mensajería (STOMP)
```

## Entrega: frontend sin integrar

Entregamos juntos el frontend de la Evaluación 1 y el backend de la Evaluación 2. Según lo acordado para esta
evaluación, `parrillada_frontend/` va sin integrar y el backend usa sus datos (productos de
`parrillada_frontend/data/productos.json` y los campos del formulario de pedido). Todos los flujos los demostramos
contra el backend real por el API Gateway (`backend/tests/demo_flujos.py`).

- Informe de los 10 módulos: [`docs/INFORME.md`](docs/INFORME.md) (también en PDF: `docs/INFORME.pdf`)
- Diagramas editables (Mermaid `.mmd` + `.svg`): `docs/diagramas/`
- Evidencias de ejecución: `docs/evidencias/`

## Arquitectura

| Servicio | Puerto | Tecnología | Responsabilidad | Base de datos |
| --- | --- | --- | --- | --- |
| gateway | 8000 | FastAPI + httpx | Única entrada: rutas explícitas, sesión, roles, rate limit, correlation id | — |
| auth | 8100 | FastAPI + Motor | Registro, login (bcrypt), introspección y logout | `auth_db` |
| clients | 9004 | FastAPI + Motor | Perfil del cliente (nombre, correo, dirección) | `clients_db` |
| inventory | 9001 | FastAPI + Motor | Catálogo, stock y reservas atómicas | `inventory_db` |
| orders | 9002 | FastAPI + Motor | Pedidos, total calculado en servidor, estados, analítica | `orders_db` |
| payments | 9003 | FastAPI + Motor | Inicio de pago y webhook firmado (HMAC) e idempotente | `payments_db` |
| graphql | 4000 | Node + Apollo | Agregaciones privadas (`misPedidos`, `resumenPedido`, `analitica`) | ninguna |
| Vault | 8200 | HashiCorp Vault (dev) | Secretos de integración, una política por servicio | — |

- Todos los servicios internos escuchan solo en `127.0.0.1` y rechazan con **403** cualquier llamada sin el
  secreto de su tramo (`X-Service-Name` + `X-Service-Secret`). Cada tramo (ej. `gateway -> orders`,
  `payments -> orders`) tiene un secreto distinto, guardado en Vault.
- El gateway descarta las cabeceras de identidad del cliente y envía solo la identidad verificada con auth
  (`X-User-Id`, `X-User-Roles`).
- Cada servicio lee de Vault solo su propia ruta (`secret/parrillada/<servicio>`) con un token de política
  de solo lectura.
- Se ejecuta en local, sin Docker.

## Requisitos

- Python 3.11 con el entorno `.venv` en la raíz del repositorio
- Node.js 18 o superior
- MongoDB local en `localhost:27017`
- Vault (`vault.exe`) en el PATH

## Puesta en marcha

Todo se ejecuta desde la carpeta `parrillada/backend/` en PowerShell (desde `parrillada/`: `cd backend`).

1. Dependencias (una vez):

   ```powershell
   cd backend
   ..\..\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   cd services\graphql; npm install; cd ..\..
   ```

2. Vault en modo dev, en una ventana aparte que queda abierta (el valor del token lo inventa usted):

   ```powershell
   vault server -dev -dev-root-token-id="<token-root-de-desarrollo>"
   ```

3. Cargar los secretos (genera un secreto por tramo, políticas y un token por servicio en `backend/.tokens`,
   archivo que no se sube al repositorio). Volver a ejecutarlo rota todos los secretos:

   ```powershell
   $env:VAULT_ADDR = "http://127.0.0.1:8200"
   $env:VAULT_TOKEN = "<token-root-de-desarrollo>"
   python vault/cargar_secretos.py
   ```

4. Datos de prueba (productos del frontend con stock y un usuario operador):

   ```powershell
   $env:OPERADOR_PASSWORD = "<clave-de-prueba>"
   python datos/cargar_datos.py
   ```

5. Iniciar y detener los servicios:

   ```powershell
   .\iniciar.ps1     
   .\detener.ps1
   ```

   Vault en modo dev guarda en memoria: si se cierra, repetir los pasos 2, 3 y 5.

## Pruebas

Con todo levantado, desde `parrillada/backend/`:

```powershell
$env:OPERADOR_PASSWORD = "<clave-de-prueba>"
python -m pytest tests -v
```

- `backend/tests/test_seguridad.py`: anónimo 200, sin sesión 401, rol sin permiso 403, acceso directo 403,
  cabeceras falsas, bcrypt, logout, pago con monto alterado, webhook con firma inválida, duplicado y rechazado,
  mínimo privilegio en Vault.
- `backend/tests/test_negocio.py`: total calculado en servidor, stock insuficiente 409, compras simultáneas,
  idempotencia, pedido ajeno 404, transición inválida 409, anulación que libera stock, agregaciones GraphQL,
  campos restringidos, límite de profundidad y paginación.
- `backend/tests/test_zz_limite_solicitudes.py`: rate limit del login (429). Deja el login bloqueado 1 minuto:
  esperar antes de volver a correr las pruebas.
- `backend/tests/prueba_inventory_caido.py`: con inventory detenido, el gateway responde 503 controlado y GraphQL
  devuelve error parcial.
- `backend/tests/demo_flujos.py`: recorrido completo (compra, pago, despacho, controles de acceso y logout) mostrando cada respuesta.
- `backend/tests/prueba_carga.py`: p50, p95, throughput y errores (iniciar el gateway con `$env:LIMITE_POR_MINUTO="100000"`).

## Rutas del gateway

| Verbo | Ruta | Acceso | Destino |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/registro` | anónimo | auth |
| POST | `/api/v1/auth/login` | anónimo | auth |
| POST | `/api/v1/auth/logout` | autenticado | auth |
| GET, PUT | `/api/v1/clientes/me` | autenticado | clients |
| GET | `/api/v1/clientes`, `/api/v1/clientes/{id}` | operador | clients |
| GET | `/api/v1/productos`, `/api/v1/productos/{id}` | anónimo | inventory |
| POST, PUT | `/api/v1/productos`, `/api/v1/productos/{id}` | operador | inventory |
| PATCH | `/api/v1/productos/{id}/stock` | operador | inventory |
| POST | `/api/v1/pedidos` | cliente | orders |
| GET | `/api/v1/pedidos`, `/api/v1/pedidos/{id}` | autenticado (solo los propios) | orders |
| POST | `/api/v1/pedidos/{id}/anular` | autenticado (solo los propios) | orders |
| PATCH | `/api/v1/pedidos/{id}/estado` | operador | orders |
| POST | `/api/v1/pagos` | cliente | payments |
| GET | `/api/v1/pagos/{id}` | autenticado (solo los propios) | payments |
| POST | `/api/v1/pagos/webhook` | proveedor (firma HMAC) | payments |
| POST | `/api/v1/pagos/{id}/reintentar-aviso` | operador | payments |
| POST | `/api/v1/graphql` | autenticado | graphql |

Cualquier otra ruta o verbo responde 404. La documentación interactiva de cada servicio está en
`http://127.0.0.1:<puerto>/docs` (solo accesible desde el propio equipo).

## Limitaciones declaradas

- Comunicación en HTTP local, sin TLS: es un entorno de desarrollo en un solo equipo. En un despliegue real,
  el gateway iría detrás de HTTPS y los tramos internos con TLS.
- Vault en modo dev (en memoria). Los secretos se recargan con `backend/vault/cargar_secretos.py`.
- MongoDB local sin autenticación: la separación es una base por servicio. En producción cada servicio tendría
  su propio usuario de base de datos con permiso solo sobre su base.
- El proveedor de pagos es un adaptador de prueba: respeta contrato, firma HMAC y estados; las pruebas lo simulan.

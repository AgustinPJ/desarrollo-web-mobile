"""
Pruebas de seguridad (M4, M6, M7, M10): gateway, auth, clients, payments y Vault.
Cada prueba indica el caso de validación de la pauta que demuestra.
"""
import uuid

import httpx
from pymongo import MongoClient

from conftest import (SERVICIOS_DIRECTOS, VAULT_ADDR, crear_pedido, enviar_webhook, registrar_y_entrar,
                      token_vault)


# ---------- Acceso anónimo, sesión y roles ----------

def test_catalogo_anonimo_200_solo_campos_publicos(api):
    r = api.get("/api/v1/productos")
    assert r.status_code == 200
    producto = r.json()[0]
    assert set(producto) == {"id", "nombre", "linea", "formato", "descripcion", "precio", "disponible"}
    assert "stock" not in producto


def test_operacion_protegida_sin_sesion_401(api):
    assert api.get("/api/v1/clientes/me").status_code == 401
    assert api.post("/api/v1/pedidos", json={}).status_code == 401


def test_token_inventado_401(api):
    r = api.get("/api/v1/clientes/me", headers={"Authorization": "Bearer token-inventado"})
    assert r.status_code == 401


def test_cliente_en_operacion_de_administracion_403(api, cliente_a):
    assert api.get("/api/v1/clientes", headers=cliente_a["headers"]).status_code == 403
    nuevo = {"id": "PARR-99", "nombre": "Prueba", "linea": "Parrilla Directa", "formato": "1 kg",
             "descripcion": "No debería crearse", "precio": 1000, "stock": 5}
    assert api.post("/api/v1/productos", json=nuevo, headers=cliente_a["headers"]).status_code == 403


def test_cabeceras_de_identidad_falsas_se_descartan(api, cliente_a):
    # El navegador intenta hacerse pasar por operador: el gateway ignora esas cabeceras.
    cabeceras = dict(cliente_a["headers"], **{"X-User-Roles": "operador", "X-User-Id": "otro"})
    assert api.get("/api/v1/clientes", headers=cabeceras).status_code == 403
    assert api.get("/api/v1/clientes/me", headers=cabeceras).json()["user_id"] == cliente_a["user_id"]


def test_ruta_o_verbo_no_listado_404(api, operador):
    assert api.get("/api/v1/admin/usuarios", headers=operador["headers"]).status_code == 404
    assert api.delete("/api/v1/productos/PARR-01", headers=operador["headers"]).status_code == 404


def test_respuestas_llevan_correlation_id(api):
    r = api.get("/api/v1/productos", headers={"X-Correlation-Id": "prueba-123"})
    assert r.headers["X-Correlation-Id"] == "prueba-123"


# ---------- Acceso directo a microservicios (frontera privada) ----------

def test_acceso_directo_sin_identidad_autorizada_403():
    falsas = {"X-User-Id": "cualquiera", "X-User-Roles": "operador"}
    for servicio, ruta in [("clients", "/clientes"), ("orders", "/orders"), ("payments", "/pagos/x"),
                           ("inventory", "/productos")]:
        r = httpx.get(SERVICIOS_DIRECTOS[servicio] + ruta, headers=falsas)
        assert r.status_code == 403, servicio
    r = httpx.post(SERVICIOS_DIRECTOS["graphql"] + "/graphql", json={"query": "{ misPedidos { total } }"},
                   headers=falsas)
    assert r.status_code == 403


def test_acceso_directo_con_secreto_equivocado_403():
    cabeceras = {"X-Service-Name": "gateway", "X-Service-Secret": "adivinado", "X-User-Id": "x"}
    r = httpx.get(SERVICIOS_DIRECTOS["clients"] + "/clientes/me", headers=cabeceras)
    assert r.status_code == 403


def test_vault_minimo_privilegio_cada_servicio_lee_solo_lo_suyo():
    # Con el token de payments no se pueden leer los secretos del gateway.
    r = httpx.get(f"{VAULT_ADDR}/v1/secret/data/parrillada/gateway",
                  headers={"X-Vault-Token": token_vault("payments")})
    assert r.status_code == 403
    r = httpx.get(f"{VAULT_ADDR}/v1/secret/data/parrillada/payments",
                  headers={"X-Vault-Token": token_vault("payments")})
    assert r.status_code == 200


# ---------- Auth y clients ----------

def test_contrasena_guardada_con_hash_bcrypt_y_nunca_devuelta(api, cliente_a):
    usuario = MongoClient("mongodb://localhost:27017").auth_db.usuarios.find_one({"email": cliente_a["correo"]})
    assert usuario["password_hash"].startswith("$2b$")
    assert cliente_a["clave"] not in usuario["password_hash"]
    perfil = api.get("/api/v1/clientes/me", headers=cliente_a["headers"]).json()
    assert "password" not in str(perfil).lower()


def test_registro_con_correo_repetido_409(api, cliente_a):
    r = api.post("/api/v1/auth/registro", json={"nombre": "Copia", "correo": cliente_a["correo"],
                                                "direccion": "Calle Falsa 123", "password": "OtraClave123"})
    assert r.status_code == 409


def test_registro_no_permite_elegir_rol(api):
    correo = f"intruso.{uuid.uuid4().hex[:6]}@correo.cl"
    r = api.post("/api/v1/auth/registro", json={"nombre": "Intruso", "correo": correo, "direccion": "Calle 123",
                                                "password": "ClaveSegura123", "roles": ["operador"]})
    assert r.status_code == 201
    assert r.json()["roles"] == ["cliente"]


def test_login_fallido_no_revela_si_el_correo_existe(api, cliente_a):
    r1 = api.post("/api/v1/auth/login", json={"correo": cliente_a["correo"], "password": "incorrecta"})
    r2 = api.post("/api/v1/auth/login", json={"correo": "noexiste@correo.cl", "password": "incorrecta"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_logout_revoca_la_sesion(api):
    usuario = registrar_y_entrar(api, "Pedro Soto")
    assert api.get("/api/v1/clientes/me", headers=usuario["headers"]).status_code == 200
    assert api.post("/api/v1/auth/logout", headers=usuario["headers"]).status_code == 200
    assert api.get("/api/v1/clientes/me", headers=usuario["headers"]).status_code == 401


def test_cliente_edita_solo_su_perfil_y_no_su_correo(api, cliente_a):
    r = api.put("/api/v1/clientes/me", headers=cliente_a["headers"],
                json={"nombre": "Carlos Silva M.", "direccion": "Pasaje Los Robles 55", "correo": "otro@correo.cl"})
    assert r.status_code == 200
    assert r.json()["direccion"] == "Pasaje Los Robles 55"
    assert r.json()["correo"] == cliente_a["correo"]


def test_cliente_no_ve_perfil_ajeno(api, cliente_a, cliente_b):
    r = api.get(f"/api/v1/clientes/{cliente_b['user_id']}", headers=cliente_a["headers"])
    assert r.status_code == 403


def test_listado_de_operador_minimiza_datos_personales(api, operador, cliente_a):
    r = api.get("/api/v1/clientes", headers=operador["headers"])
    assert r.status_code == 200
    assert all(set(c) == {"user_id", "nombre", "correo"} for c in r.json()["items"])


# ---------- Pagos ----------

def test_pago_con_monto_alterado_usa_el_total_del_servidor(api, cliente_a):
    pedido = crear_pedido(api, cliente_a, "SMOK-02", 2).json()
    r = api.post("/api/v1/pagos", json={"order_id": pedido["id"], "monto": 1}, headers=cliente_a["headers"])
    assert r.status_code == 201
    assert r.json()["monto"] == pedido["total"] == 2 * 19990


def test_no_se_puede_pagar_pedido_ajeno(api, cliente_a, cliente_b):
    pedido = crear_pedido(api, cliente_a).json()
    r = api.post("/api/v1/pagos", json={"order_id": pedido["id"]}, headers=cliente_b["headers"])
    assert r.status_code == 404


def test_webhook_con_firma_invalida_401(api, cliente_a):
    pedido = crear_pedido(api, cliente_a).json()
    pago = api.post("/api/v1/pagos", json={"order_id": pedido["id"]}, headers=cliente_a["headers"]).json()
    evento = {"event_id": uuid.uuid4().hex, "payment_id": pago["payment_id"], "estado": "aprobado",
              "monto": pago["monto"]}
    assert enviar_webhook(api, evento, clave="clave-falsa").status_code == 401
    r = api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_a["headers"])
    assert r.json()["estado"] == "pendiente"


def test_frontend_no_puede_confirmar_pago_por_su_cuenta(api, cliente_a):
    pedido = crear_pedido(api, cliente_a).json()
    r = api.patch(f"/api/v1/pedidos/{pedido['id']}/estado", json={"estado": "pagado"}, headers=cliente_a["headers"])
    assert r.status_code == 403


def test_webhook_aprobado_marca_pagado_y_duplicado_no_cambia_nada(api, cliente_a):
    pedido = crear_pedido(api, cliente_a).json()
    pago = api.post("/api/v1/pagos", json={"order_id": pedido["id"]}, headers=cliente_a["headers"]).json()
    evento = {"event_id": uuid.uuid4().hex, "payment_id": pago["payment_id"], "estado": "aprobado",
              "monto": pago["monto"]}

    r = enviar_webhook(api, evento)
    assert r.status_code == 200 and r.json()["resultado"] == "procesado"
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_a["headers"]).json()["estado"] == "pagado"

    r = enviar_webhook(api, evento)  # el proveedor reintenta el mismo aviso
    assert r.status_code == 200 and r.json()["resultado"] == "duplicado"
    historial = api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_a["headers"]).json()["historial"]
    assert [h["estado"] for h in historial].count("pagado") == 1


def test_webhook_con_monto_distinto_se_rechaza(api, cliente_a):
    pedido = crear_pedido(api, cliente_a).json()
    pago = api.post("/api/v1/pagos", json={"order_id": pedido["id"]}, headers=cliente_a["headers"]).json()
    evento = {"event_id": uuid.uuid4().hex, "payment_id": pago["payment_id"], "estado": "aprobado", "monto": 1}
    assert enviar_webhook(api, evento).status_code == 422


def test_pago_rechazado_anula_pedido_y_libera_stock(api, cliente_a, operador):
    stock_antes = api.get("/api/v1/productos/SMOK-01", headers=operador["headers"]).json()["stock"]
    pedido = crear_pedido(api, cliente_a, "SMOK-01", 1).json()
    pago = api.post("/api/v1/pagos", json={"order_id": pedido["id"]}, headers=cliente_a["headers"]).json()
    evento = {"event_id": uuid.uuid4().hex, "payment_id": pago["payment_id"], "estado": "rechazado",
              "monto": pago["monto"]}
    assert enviar_webhook(api, evento).status_code == 200
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_a["headers"]).json()["estado"] == "anulado"
    assert api.get("/api/v1/productos/SMOK-01", headers=operador["headers"]).json()["stock"] == stock_antes

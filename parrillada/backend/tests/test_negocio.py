"""
Pruebas de negocio (M3, M8, M10): inventory, orders y GraphQL Gateway.
"""
from concurrent.futures import ThreadPoolExecutor

import httpx

from conftest import GATEWAY, crear_pedido, enviar_webhook, fecha_entrega


def graphql(api, usuario, consulta, variables=None):
    return api.post("/api/v1/graphql", json={"query": consulta, "variables": variables or {}},
                    headers=usuario["headers"])


# ---------- Pedidos ----------

def test_total_lo_calcula_el_servidor(api, cliente_a):
    r = crear_pedido(api, cliente_a, "PARR-01", 3, total=10, precio=1)
    assert r.status_code == 201
    pedido = r.json()
    assert pedido["items"][0]["precio_unitario"] == 14990
    assert pedido["total"] == 3 * 14990
    assert pedido["estado"] == "pendiente"


def test_producto_sin_stock_409(api, cliente_a):
    r = crear_pedido(api, cliente_a, "PARR-03", 1)  # en el frontend figura "no disponible"
    assert r.status_code == 409


def test_fecha_de_entrega_pasada_422(api, cliente_a):
    r = crear_pedido(api, cliente_a, "PARR-01", 1, fecha_entrega="2020-01-01")
    assert r.status_code == 422


def test_dos_compras_simultaneas_no_venden_mas_stock_del_que_hay(api, cliente_a, operador):
    assert api.patch("/api/v1/productos/PACK-02/stock", json={"stock": 3},
                     headers=operador["headers"]).status_code == 200

    def comprar(_):
        with httpx.Client(base_url=GATEWAY, timeout=10.0) as c:
            return crear_pedido(c, cliente_a, "PACK-02", 1).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(comprar, range(8)))
    assert resultados.count(201) == 3
    assert resultados.count(409) == 5
    assert api.get("/api/v1/productos/PACK-02", headers=operador["headers"]).json()["stock"] == 0
    api.patch("/api/v1/productos/PACK-02/stock", json={"stock": 20}, headers=operador["headers"])


def test_misma_idempotency_key_no_duplica_el_pedido(api, cliente_a):
    cabeceras = dict(cliente_a["headers"], **{"Idempotency-Key": "pedido-prueba-abc"})
    cuerpo = {"items": [{"producto_id": "PARR-02", "cantidad": 1}],
              "direccion_entrega": "Av. Las Parcelas 1234", "fecha_entrega": fecha_entrega()}
    r1 = api.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras)
    r2 = api.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras)
    assert r1.status_code == 201
    assert r2.json()["id"] == r1.json()["id"]


def test_misma_idempotency_key_simultanea_crea_un_solo_pedido(api, cliente_a, operador):
    assert api.patch("/api/v1/productos/SMOK-01/stock", json={"stock": 10},
                     headers=operador["headers"]).status_code == 200
    cabeceras = dict(cliente_a["headers"], **{"Idempotency-Key": "pedido-simultaneo-xyz"})
    cuerpo = {"items": [{"producto_id": "SMOK-01", "cantidad": 2}],
              "direccion_entrega": "Av. Las Parcelas 1234", "fecha_entrega": fecha_entrega()}

    def enviar(_):
        with httpx.Client(base_url=GATEWAY, timeout=10.0) as c:
            return c.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras)

    with ThreadPoolExecutor(max_workers=4) as pool:
        respuestas = list(pool.map(enviar, range(4)))
    assert [r.status_code for r in respuestas] == [201] * 4
    assert len({r.json()["id"] for r in respuestas}) == 1
    # El stock se descuenta una sola vez.
    assert api.get("/api/v1/productos/SMOK-01", headers=operador["headers"]).json()["stock"] == 8
    api.patch("/api/v1/productos/SMOK-01/stock", json={"stock": 20}, headers=operador["headers"])


def test_pedido_ajeno_404_sin_revelar_datos(api, cliente_a, cliente_b):
    pedido = crear_pedido(api, cliente_a).json()
    r = api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_b["headers"])
    assert r.status_code == 404
    assert "direccion" not in r.text
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_a["headers"]).status_code == 200


def test_listado_de_cliente_solo_trae_sus_pedidos(api, cliente_a, cliente_b):
    crear_pedido(api, cliente_b)
    pedidos = api.get("/api/v1/pedidos", headers=cliente_b["headers"]).json()["items"]
    assert pedidos and all(p["user_id"] == cliente_b["user_id"] for p in pedidos)


def test_transicion_invalida_409(api, cliente_a, operador):
    pedido = crear_pedido(api, cliente_a).json()
    r = api.patch(f"/api/v1/pedidos/{pedido['id']}/estado", json={"estado": "entregado"},
                  headers=operador["headers"])
    assert r.status_code == 409


def test_anular_no_borra_y_libera_stock(api, cliente_a, operador):
    antes = api.get("/api/v1/productos/PACK-01", headers=operador["headers"]).json()["stock"]
    pedido = crear_pedido(api, cliente_a, "PACK-01", 2).json()
    assert api.get("/api/v1/productos/PACK-01", headers=operador["headers"]).json()["stock"] == antes - 2
    r = api.post(f"/api/v1/pedidos/{pedido['id']}/anular", headers=cliente_a["headers"])
    assert r.status_code == 200 and r.json()["estado"] == "anulado"
    assert api.get(f"/api/v1/pedidos/{pedido['id']}", headers=cliente_a["headers"]).status_code == 200
    assert api.get("/api/v1/productos/PACK-01", headers=operador["headers"]).json()["stock"] == antes
    # Anular dos veces no devuelve stock dos veces.
    assert api.post(f"/api/v1/pedidos/{pedido['id']}/anular", headers=cliente_a["headers"]).status_code == 409


# ---------- GraphQL Gateway ----------

CONSULTA_MIS_PEDIDOS = """
query($limit: Int) {
  misPedidos(limit: $limit) {
    total
    items { id estado total direccionEntrega items { productoId cantidad subtotal producto { nombre linea disponible } } }
  }
}"""


def test_graphql_agrega_orders_e_inventory(api, cliente_b):
    r = graphql(api, cliente_b, CONSULTA_MIS_PEDIDOS, {"limit": 5})
    assert r.status_code == 200
    datos = r.json()
    assert "errors" not in datos
    item = datos["data"]["misPedidos"]["items"][0]["items"][0]
    assert item["producto"]["nombre"]  # viene de inventory
    assert item["subtotal"] > 0         # viene de orders


def test_graphql_resumen_pedido_con_nombre_del_cliente(api, cliente_a):
    pedido = crear_pedido(api, cliente_a).json()
    r = graphql(api, cliente_a, "query($id: ID!) { resumenPedido(id: $id) { estado cliente { nombre } "
                                "items { producto { nombre } } } }", {"id": pedido["id"]})
    datos = r.json()["data"]["resumenPedido"]
    assert datos["cliente"]["nombre"]  # viene de clients
    assert datos["items"][0]["producto"]["nombre"]


def test_graphql_pedido_ajeno_devuelve_null(api, cliente_a, cliente_b):
    pedido = crear_pedido(api, cliente_a).json()
    r = graphql(api, cliente_b, "query($id: ID!) { resumenPedido(id: $id) { direccionEntrega } }", {"id": pedido["id"]})
    assert r.json()["data"]["resumenPedido"] is None


def test_graphql_campo_restringido_para_el_rol(api, cliente_a):
    r = graphql(api, cliente_a, "{ misPedidos(limit: 1) { items { items { producto { nombre stock } } } } }")
    datos = r.json()
    assert any(e["extensions"]["code"] == "FORBIDDEN" for e in datos["errors"])
    assert "stock" not in str(datos["data"]).replace("'stock': None", "")


def test_graphql_analitica_solo_operador(api, cliente_a, operador):
    # Se paga un pedido para que exista al menos una venta en el reporte.
    pedido = crear_pedido(api, cliente_a, "PARR-02", 1).json()
    pago = api.post("/api/v1/pagos", json={"order_id": pedido["id"]}, headers=cliente_a["headers"]).json()
    enviar_webhook(api, {"event_id": "venta-" + pedido["id"], "payment_id": pago["payment_id"],
                         "estado": "aprobado", "monto": pago["monto"]})
    consulta = "{ analitica(dias: 30) { ventasPorDia { fecha pedidos monto } topProductos { productoId unidades producto { nombre } } } }"
    r = graphql(api, cliente_a, consulta)
    assert r.json()["data"]["analitica"] is None
    assert r.json()["errors"][0]["extensions"]["code"] == "FORBIDDEN"
    r = graphql(api, operador, consulta)
    assert "errors" not in r.json()
    assert r.json()["data"]["analitica"]["ventasPorDia"]


def test_graphql_consulta_demasiado_profunda_rechazada(api, cliente_a):
    # Profundidad 5 (el límite es 4): se rechaza en la validación, sin llamar a ningún servicio.
    r = graphql(api, cliente_a, "{ misPedidos { items { items { producto { nombre { largo } } } } } }")
    assert r.status_code == 400
    assert "exceeds maximum operation depth of 4" in r.text


def test_graphql_consulta_mas_profunda_permitida_funciona(api, cliente_a):
    r = graphql(api, cliente_a, "{ misPedidos { items { items { producto { nombre } } } } }")
    assert r.status_code == 200 and "errors" not in r.json()


def test_graphql_limite_de_paginacion(api, cliente_a):
    r = graphql(api, cliente_a, "{ misPedidos(limit: 500) { total } }")
    assert r.json()["errors"][0]["extensions"]["code"] == "PARAMETRO_INVALIDO"


def test_graphql_no_tiene_mutaciones(api, cliente_a):
    # Las reglas transaccionales quedan en orders: GraphQL es solo de consulta.
    r = graphql(api, cliente_a, 'mutation { crearPedido(id: "x") { id } }')
    assert r.status_code == 400

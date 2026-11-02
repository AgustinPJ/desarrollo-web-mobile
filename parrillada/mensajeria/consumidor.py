
import argparse
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation

import stomp

DESTINO = "/queue/pedidos"
MONTO_MAXIMO = Decimal("99999999.99")  


def interpretar(cuerpo: str, headers: dict):
    formato = headers.get("x-formato", "").lower()
    tipo_mime = headers.get("content-type", "").lower()
    if not formato:
        if "application/json" in tipo_mime:
            formato = "json"
        elif "application/xml" in tipo_mime or "text/xml" in tipo_mime:
            formato = "xml"
        else:
            formato = "texto"
    if formato == "texto":
        return formato, cuerpo
    if formato == "fijo":
        if len(cuerpo) != 36:
            raise ValueError(f"Registro de ancho fijo inválido: {len(cuerpo)} caracteres, se esperan 36")
        identificador = cuerpo[0:6]
        cliente = cuerpo[6:26].rstrip()
        monto = cuerpo[26:36]
        if not (identificador.isascii() and identificador.isdigit()
                and monto[:7].isdigit() and monto[7] == "." and monto[8:].isdigit()):
            raise ValueError("Campos numéricos de ancho fijo inválidos")
        return formato, {"id": identificador, "cliente": cliente, "monto": monto}
    if formato == "json":
        return formato, json.loads(cuerpo)
    if formato == "xml":
        raiz = ET.fromstring(cuerpo)
        if raiz.tag != "pedido":
            raise ValueError("El nodo raíz del XML debe ser <pedido>")
        return formato, {elemento.tag: elemento.text for elemento in raiz}
    raise ValueError(f"Formato no soportado: {formato}")


def validar_pedido(pedido) -> dict:
    if not isinstance(pedido, dict):
        raise ValueError("El pedido debe ser un objeto con id, cliente y monto")
    for campo in ("id", "cliente", "monto"):
        if campo not in pedido or pedido[campo] in (None, ""):
            raise ValueError(f"Al pedido le falta el campo '{campo}'")

    identificador = str(pedido["id"]).strip()
    if not (identificador.isascii() and identificador.isdigit()):
        raise ValueError(f"Id de pedido inválido: {identificador}")
    identificador = identificador.lstrip("0") or "0"  

    cliente = str(pedido["cliente"]).strip()
    if not cliente:
        raise ValueError("El cliente no puede venir vacío")

    try:
        monto = Decimal(str(pedido["monto"]))
    except InvalidOperation:
        raise ValueError(f"Monto no válido: {pedido['monto']}")
    if not monto.is_finite() or monto <= 0 or monto > MONTO_MAXIMO:
        raise ValueError(f"El monto debe estar entre 0.01 y {MONTO_MAXIMO}")
    if monto != monto.quantize(Decimal("0.01")):
        raise ValueError("El monto no puede tener más de 2 decimales")

    return {"id": identificador, "cliente": cliente, "monto": monto.quantize(Decimal("0.01"))}


class Escuchador(stomp.ConnectionListener):
    def __init__(self, conexion):
        self.conexion = conexion
        self.pagos = {}  

    def on_error(self, frame):
        print(f"ERROR del broker: {frame.body}")

    def on_disconnected(self):
        print("Conexión STOMP cerrada")

    def on_message(self, frame):
        ack_id = frame.headers["ack"]
        try:
            formato, contenido = interpretar(frame.body, frame.headers)
            print(f"\n[RECIBIDO] formato={formato}")

            if formato == "texto":
                
                print(f"Aviso: {contenido}")
                self.conexion.ack(id=ack_id)
                return

            pedido = validar_pedido(contenido)
            if pedido["id"] in self.pagos:
                
                print(f"[DUPLICADO] El pedido {pedido['id']} ya estaba pagado, no se cobra otra vez")
                self.conexion.ack(id=ack_id)
                return

            pago = {
                "pedido": pedido["id"],
                "cliente": pedido["cliente"],
                "monto": str(pedido["monto"]),
                "estado": "aprobado",
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.pagos[pedido["id"]] = pago
            print("[PAGO REGISTRADO]")
            print(json.dumps(pago, ensure_ascii=False, indent=2))
            self.conexion.ack(id=ack_id)
        except (ValueError, ET.ParseError) as exc:
            print(f"[MENSAJE NO VÁLIDO] {exc}")
            self.conexion.nack(id=ack_id)
        except Exception as exc:
            print(f"[ERROR AL PROCESAR] {exc}")
            self.conexion.nack(id=ack_id)


def main():
    parser = argparse.ArgumentParser(description="Consumidor STOMP de pagos")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=61613)
    args = parser.parse_args()

    usuario = os.getenv("BROKER_USUARIO")
    clave = os.getenv("BROKER_CLAVE")
    if not usuario or not clave:
        parser.error("Faltan las variables de entorno BROKER_USUARIO y BROKER_CLAVE")

    conexion = stomp.Connection12([(args.host, args.port)], vhost="/")
    conexion.set_listener("pagos", Escuchador(conexion))
    try:
        conexion.connect(usuario, clave, wait=True)
        conexion.subscribe(
            destination=DESTINO, id="lector-pagos",
            ack="client-individual", headers={"activemq.prefetchSize": "1"}
        )
        print(f"Escuchando {DESTINO}. Presiona Ctrl+C para salir.")
        while conexion.is_connected():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDeteniendo consumidor...")
    except stomp.exception.ConnectFailedException:
        print(f"No se pudo conectar al broker en {args.host}:{args.port}. ¿Está corriendo ActiveMQ?")
    finally:
        if conexion.is_connected():
            conexion.disconnect()


if __name__ == "__main__":
    main()

import argparse
import json
import os
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

import stomp

DESTINO = "/queue/pedidos"
MONTO_MAXIMO = Decimal("99999999.99")


def construir_mensaje(formato: str, pedido: dict, texto: str) -> tuple[str, str]:
    if formato == "texto":
        return texto, "text/plain; charset=utf-8"
    if formato == "fijo":
        identificador = str(pedido["id"])
        cliente = str(pedido["cliente"])
        monto_campo = f"{Decimal(pedido['monto']):010.2f}"
        if len(identificador) > 6:
            raise ValueError("En formato fijo, --id debe tener hasta 6 dígitos")
        if len(cliente) > 20 or not cliente.isascii():
            raise ValueError("En formato fijo, --cliente admite hasta 20 caracteres sin tildes ni ñ")
        return f"{identificador.zfill(6)}{cliente:<20}{monto_campo}", "text/plain; charset=utf-8"
    if formato == "json":
        return json.dumps(pedido, ensure_ascii=False), "application/json; charset=utf-8"
    if formato == "xml":
        raiz = ET.Element("pedido")
        for clave, valor in pedido.items():
            ET.SubElement(raiz, clave).text = str(valor)
        return ET.tostring(raiz, encoding="unicode"), "application/xml; charset=utf-8"
    raise ValueError(f"Formato desconocido: {formato}")


def validar_pedido(identificador: str, cliente: str, monto_texto: str) -> dict:
    identificador = identificador.strip()
    if not (identificador.isascii() and identificador.isdigit()):
        raise ValueError(f"El id debe ser numérico: {identificador}")

    cliente = cliente.strip()
    if not cliente:
        raise ValueError("El cliente no puede venir vacío")

    try:
        monto = Decimal(monto_texto)
    except InvalidOperation:
        raise ValueError(f"Monto no válido: {monto_texto}")
    if not monto.is_finite() or monto <= 0 or monto > MONTO_MAXIMO:
        raise ValueError(f"El monto debe estar entre 0.01 y {MONTO_MAXIMO}")
    if monto != monto.quantize(Decimal("0.01")):
        raise ValueError("El monto no puede tener más de 2 decimales")

    return {"id": identificador, "cliente": cliente, "monto": str(monto.quantize(Decimal("0.01")))}


def main():
    parser = argparse.ArgumentParser(description="Productor STOMP de pedidos")
    parser.add_argument("--formato", choices=["texto", "fijo", "xml", "json"], required=True)
    parser.add_argument("--mensaje", default="Hola desde el productor STOMP")
    parser.add_argument("--id", default="123")
    parser.add_argument("--cliente", default="Ernesto Vivanco")
    parser.add_argument("--monto", default="123.45")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=61613)
    args = parser.parse_args()

    usuario = os.getenv("BROKER_USUARIO")
    clave = os.getenv("BROKER_CLAVE")
    if not usuario or not clave:
        parser.error("Faltan las variables de entorno BROKER_USUARIO y BROKER_CLAVE")

    try:
        pedido = validar_pedido(args.id, args.cliente, args.monto)
        cuerpo, mime = construir_mensaje(args.formato, pedido, args.mensaje)
    except ValueError as exc:
        parser.error(str(exc))

    conexion = stomp.Connection12([(args.host, args.port)], vhost="/")
    try:
        conexion.connect(usuario, clave, wait=True)
        conexion.send(
            destination=DESTINO,
            body=cuerpo,
            headers={
                "content-type": mime,
                "x-formato": args.formato,
                "persistent": "true",
            },
        )
        print(f"Mensaje enviado a {DESTINO} (formato={args.formato}):\n{cuerpo}")
    except stomp.exception.ConnectFailedException:
        print(f"No se pudo conectar al broker en {args.host}:{args.port}. ¿Está corriendo ActiveMQ?")
    finally:
        if conexion.is_connected():
            conexion.disconnect()


if __name__ == "__main__":
    main()
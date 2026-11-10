# ADR-001: Analítica dentro de orders y sin gRPC

Estado: aceptada · Responsable: David León · Fecha: 2026-11-09

## Contexto

- La Tienda del Fuego vende 7 productos en 3 líneas, con despacho a domicilio. Proyección: hasta 20 usuarios
  concurrentes en horario punta y unos cientos de pedidos al mes.
- El operador necesita un reporte pequeño: ventas por día y top de productos (M9).
- La comunicación interna es de petición y respuesta: reservar stock, leer un pedido, marcar pagado.
  No hay flujos continuos de eventos (por ejemplo, seguimiento del despacho en tiempo real).

## Alternativas

1. Servicio de analítica separado con su propia base, alimentado por eventos.
2. Analítica como consulta de agregación dentro de orders, expuesta solo a GraphQL y solo al operador.
3. gRPC unary entre orders e inventory para la reserva de stock.
4. gRPC con streaming para el estado del despacho.

## Decisión

- Se elige la alternativa 2: `GET /orders/analitica` (solo llamable por graphql, rol operador) agrega con
  `$group` en Mongo y devuelve montos y unidades, sin datos personales. GraphQL la expone como `analitica`.
- No se implementa gRPC. Las llamadas internas siguen en REST/JSON con timeout de 5 s y secreto por tramo.

## Justificación y medición

- Un reporte diario sobre cientos de pedidos no necesita un subsistema aparte ni big data (la pauta lo indica).
- gRPC aporta contratos tipados y streaming; el caso no tiene streaming y el cuello de botella no es la
  serialización JSON. Agregarlo sumaría .proto, servidor y cliente sin una necesidad medida.
- Prueba de carga reproducible: `tests/prueba_carga.py --usuarios 20 --segundos 30` (proyección de horario punta,
  no medición de producción). Resultado de referencia en el equipo de desarrollo:

| Usuarios | Duración | Solicitudes | Throughput | p50 | p95 | Errores | CPU (7 servicios) | RAM |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 30 s | 1.675 | 55,5 req/s | 337 ms | 602 ms | 0 % | 113 % prom. de 400 % (4 núcleos) | ~543 MB |

  Objetivo declarado: p95 < 1.000 ms y 0 % de errores con 20 usuarios. Se cumple sin gRPC.
  Detalle y entorno en `docs/evidencias/prueba-carga.txt`. Se puede repetir en el equipo de entrega.

## Consecuencias

- Si aparece seguimiento del despacho en tiempo real o el volumen crece 10 veces, revisar esta decisión:
  servicio de analítica separado y gRPC con streaming de servidor hacia un consumidor privado.

# Rutas y secretos de integración (M6)

Responsable: Agustín Pacheco. La matriz de rutas completa está en el README y en `services/gateway/main.py` (lista `RUTAS`).

## Identidad entre componentes

- Credencial del usuario: token Bearer opaco (32 bytes aleatorios) emitido por auth. En `auth_db` se guarda solo
  su SHA-256. Expira a los 30 minutos y el logout lo revoca.
- Credencial entre sistemas: secreto por tramo enviado en `X-Service-Name` + `X-Service-Secret`.
  El servicio destino verifica con `secrets.compare_digest` y además revisa que el llamador esté permitido
  para esa operación (ej. solo auth crea perfiles en clients; solo payments marca un pedido como pagado).
- Identidad del usuario hacia los servicios: `X-User-Id` y `X-User-Roles`, armadas por el gateway desde la
  introspección. Se confían solo cuando el tramo es `gateway`.

## Inventario de secretos (referencias simbólicas, sin valores)

| Referencia | Tipo | Emisor | Consumidor | Finalidad | Ubicación | Alcance | Rotación y revocación |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `parrillada/<destino>.entrada_<origen>` / `parrillada/<origen>.salida_<destino>` | secreto compartido por tramo (12 tramos) | `vault/cargar_secretos.py` | servicio origen y destino | autenticar la llamada interna | Vault KV v2 | un solo tramo | se rotan todos al re-ejecutar el script; reiniciar servicios |
| `parrillada/payments.clave_webhook` = `parrillada/proveedor.clave_webhook` | clave HMAC | script | payments y proveedor | verificar el aviso de pago | Vault KV v2 | solo el webhook | idem |
| token Vault por servicio | token con política de solo lectura de su ruta | script | cada servicio | leer sus secretos al arrancar | `.tokens` local (fuera del repo) | 1 ruta, 24 h | se revocan al re-ejecutar el script |
| token root de Vault | token administrador (dev) | Vault | solo el script de carga | cargar políticas y secretos | variable de entorno de la terminal | todo Vault | se cambia al reiniciar Vault dev |
| `OPERADOR_PASSWORD` | credencial de usuario de prueba | equipo | `datos/cargar_datos.py`, pruebas | crear el operador | variable de entorno | un usuario | se cambia re-ejecutando el script de datos |

## Si una clave se filtra o Vault no responde

- Filtración: ejecutar `vault/cargar_secretos.py` (genera todo de nuevo y revoca los tokens anteriores) y reiniciar
  con `iniciar.ps1`. Una sesión de usuario filtrada se revoca con logout o expira en 30 minutos.
- Vault caído: los servicios leen sus secretos solo al arrancar y los mantienen en memoria, así que siguen
  funcionando. Un servicio que se reinicia sin Vault no arranca (falla cerrado, nunca usa un valor por defecto).

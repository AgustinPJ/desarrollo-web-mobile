"""
Límite de solicitudes (M5). Va al final (nombre test_zz_) porque deja bloqueado el login de esta IP
durante un minuto: si se vuelven a correr las pruebas, esperar 60 segundos.
"""


def test_demasiados_intentos_de_login_429(api):
    codigos = [api.post("/api/v1/auth/login", json={"correo": "fuerza@bruta.cl", "password": "x"}).status_code
               for _ in range(12)]
    assert 429 in codigos
    assert codigos[-1] == 429

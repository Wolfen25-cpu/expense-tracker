"""
Pruebas de seguridad (RNF03).

Comprueban que el sistema no confia en los datos que llegan del
formulario y que las defensas estan realmente activas. Cada prueba
corresponde a un ataque o a un error concreto que podria ocurrir.
"""

from datetime import date, timedelta

from app import app, LARGO_MINIMO_CLAVE
from conftest import registrar, crear_gasto


# ---------------------------------------------------------------------
# Proteccion contra CSRF
# ---------------------------------------------------------------------
def test_un_formulario_sin_token_es_rechazado(cliente):
    """Sin token, una pagina externa podria enviar formularios a esta
    aplicacion aprovechando la sesion abierta del usuario. Aqui se
    reactiva la proteccion a proposito para comprobar que funciona."""
    registrar(cliente)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        respuesta = cliente.post("/gastos", data={
            "fecha": date.today().isoformat(), "monto": "50",
            "categoria_id": 1, "descripcion": "x", "metodo_pago": "Efectivo",
        })
        assert respuesta.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# ---------------------------------------------------------------------
# Validacion de los datos del gasto
# ---------------------------------------------------------------------
def test_monto_negativo_rechazado(cliente):
    """El formulario dice min=0, pero eso solo lo respeta el navegador."""
    registrar(cliente)
    cliente.post("/gastos", data={"fecha": date.today().isoformat(),
                                  "monto": "-500", "categoria_id": 1})
    assert "500" not in cliente.get("/gastos").get_data(as_text=True)


def test_monto_no_numerico_no_rompe_la_pagina(cliente):
    """Antes esto provocaba un error 500 del servidor."""
    registrar(cliente)
    respuesta = cliente.post("/gastos", data={"fecha": date.today().isoformat(),
                                              "monto": "abc", "categoria_id": 1},
                             follow_redirects=True)
    assert respuesta.status_code == 200
    assert "monto" in respuesta.get_data(as_text=True).lower()


def test_fecha_invalida_no_rompe_la_pagina(cliente):
    registrar(cliente)
    respuesta = cliente.post("/gastos", data={"fecha": "treinta de abril",
                                              "monto": "20", "categoria_id": 1},
                             follow_redirects=True)
    assert respuesta.status_code == 200
    assert "fecha" in respuesta.get_data(as_text=True).lower()


def test_fecha_demasiado_lejana_rechazada(cliente):
    registrar(cliente)
    lejana = (date.today() + timedelta(days=900)).isoformat()
    cliente.post("/gastos", data={"fecha": lejana, "monto": "77", "categoria_id": 1})
    assert "77.00" not in cliente.get("/gastos").get_data(as_text=True)


def test_categoria_inexistente_rechazada(cliente):
    """Sin esta validacion el gasto quedaria apuntando a una categoria
    que no existe y la pantalla fallaria al mostrarlo."""
    registrar(cliente)
    respuesta = cliente.post("/gastos", data={"fecha": date.today().isoformat(),
                                              "monto": "33", "categoria_id": "9999"},
                             follow_redirects=True)
    assert respuesta.status_code == 200
    assert "categoría" in respuesta.get_data(as_text=True).lower()


def test_no_se_puede_usar_la_categoria_privada_de_otro(cliente):
    """RNF03: las categorias personalizadas son privadas de quien las crea."""
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    pagina = cliente.get("/categorias").get_data(as_text=True)
    assert "Veterinario" in pagina
    cliente.post("/logout")

    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    # La categoria ajena no aparece en su lista
    assert "Veterinario" not in cliente.get("/categorias").get_data(as_text=True)
    # Y tampoco puede usarla aunque adivine su identificador
    respuesta = cliente.post("/gastos", data={"fecha": date.today().isoformat(),
                                              "monto": "40", "categoria_id": 9},
                             follow_redirects=True)
    assert "40.00" not in respuesta.get_data(as_text=True)


def test_metodo_de_pago_desconocido_se_guarda_como_otro(cliente):
    registrar(cliente)
    cliente.post("/gastos", data={"fecha": date.today().isoformat(), "monto": "18",
                                  "categoria_id": 1, "metodo_pago": "<script>"})
    pagina = cliente.get("/gastos").get_data(as_text=True)
    assert "<script>" not in pagina
    assert "Otro" in pagina


# ---------------------------------------------------------------------
# Cuentas de usuario
# ---------------------------------------------------------------------
def test_contrasena_corta_rechazada(cliente):
    respuesta = cliente.post("/registro", data={
        "nombre": "Ana", "correo": "ana@ejemplo.com", "contrasena": "123"})
    assert str(LARGO_MINIMO_CLAVE) in respuesta.get_data(as_text=True)


def test_correo_invalido_rechazado(cliente):
    respuesta = cliente.post("/registro", data={
        "nombre": "Ana", "correo": "esto-no-es-un-correo", "contrasena": "clave1234"})
    assert "correo" in respuesta.get_data(as_text=True).lower()


def test_el_correo_no_distingue_mayusculas(cliente):
    """Si no se normalizara, la misma persona podria crear dos cuentas y
    no poder entrar segun como escribiera su correo."""
    registrar(cliente, correo="Ana@Ejemplo.com")
    cliente.post("/logout")
    respuesta = cliente.post("/login", data={"correo": "ana@ejemplo.com",
                                             "contrasena": "clave123"},
                             follow_redirects=True)
    assert "Registrar un gasto" in respuesta.get_data(as_text=True)


def test_correo_duplicado_rechazado(cliente):
    registrar(cliente)
    cliente.post("/logout")
    respuesta = cliente.post("/registro", data={
        "nombre": "Otra", "correo": "ana@ejemplo.com", "contrasena": "clave1234"})
    assert "registrado" in respuesta.get_data(as_text=True)


def test_el_error_de_acceso_no_revela_si_el_correo_existe(cliente):
    """Mensajes distintos permitirian averiguar que correos tienen cuenta."""
    registrar(cliente)
    cliente.post("/logout")
    con_correo_real = cliente.post("/login", data={
        "correo": "ana@ejemplo.com", "contrasena": "equivocada"}).get_data(as_text=True)
    con_correo_falso = cliente.post("/login", data={
        "correo": "nadie@ejemplo.com", "contrasena": "equivocada"}).get_data(as_text=True)
    assert "Correo o contraseña incorrectos" in con_correo_real
    assert "Correo o contraseña incorrectos" in con_correo_falso


def test_cerrar_sesion_no_funciona_por_enlace(cliente):
    """Si fuera GET, bastaria una imagen en otra pagina apuntando a esta
    direccion para cerrarle la sesion al usuario."""
    registrar(cliente)
    assert cliente.get("/logout").status_code == 405


def test_la_cookie_de_sesion_no_es_accesible_desde_javascript(cliente):
    respuesta = registrar(cliente)
    cookies = respuesta.headers.getlist("Set-Cookie")
    assert any("HttpOnly" in c for c in cookies)
    assert any("Samesite=Lax" in c or "SameSite=Lax" in c for c in cookies)


def test_no_se_puede_editar_el_gasto_de_otro(cliente):
    """RNF03: comprobacion del aislamiento entre cuentas."""
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat())
    cliente.post("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    assert cliente.get("/gastos/1/editar").status_code == 404
    assert cliente.post("/gastos/1/eliminar").status_code == 404

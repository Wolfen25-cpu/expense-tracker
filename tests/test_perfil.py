"""
Pruebas del perfil del usuario: datos personales, preferencias de
localizacion, cambio de contrasena y baja de la cuenta.

Cubren tanto el funcionamiento normal como los intentos de uso indebido,
porque un perfil es una de las pantallas mas sensibles del sistema.
"""

from datetime import date

import localizacion
from app import Usuario, Gasto
from conftest import registrar, crear_gasto


# ---------------------------------------------------------------------
# Formato de montos (sin base de datos)
# ---------------------------------------------------------------------
def test_formato_americano_y_europeo():
    assert localizacion.formatear(1234.5, "USD") == "$1,234.50"
    assert localizacion.formatear(1234.5, "EUR") == "1.234,50 €"


def test_el_signo_negativo_va_delante():
    """Se lee -$25.00 y no $-25.00."""
    assert localizacion.formatear(-25, "USD") == "-$25.00"


def test_moneda_desconocida_usa_el_respaldo():
    assert localizacion.formatear(10, "XXX") == "$10.00"
    assert localizacion.moneda_valida("XXX") == localizacion.MONEDA_POR_DEFECTO
    assert localizacion.zona_valida("Marte/Olympus") == localizacion.ZONA_POR_DEFECTO
    assert localizacion.pais_valido("Atlántida") == ""


# ---------------------------------------------------------------------
# Datos y preferencias
# ---------------------------------------------------------------------
def test_el_perfil_requiere_sesion(cliente):
    respuesta = cliente.get("/perfil")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_actualizar_los_datos_del_perfil(cliente):
    registrar(cliente)
    cliente.post("/perfil", data={
        "nombre": "Ana María", "correo": "ana@ejemplo.com",
        "pais": "España", "ciudad": "Madrid",
        "moneda": "EUR", "zona_horaria": "Europe/Madrid",
    })
    usuario = Usuario.query.filter_by(correo="ana@ejemplo.com").first()
    assert usuario.nombre == "Ana María"
    assert usuario.pais == "España"
    assert usuario.moneda == "EUR"
    assert usuario.zona_horaria == "Europe/Madrid"


def test_la_moneda_elegida_se_aplica_en_toda_la_interfaz(cliente):
    """Es el punto de la funcion: no basta con guardarla, los montos
    deben mostrarse en esa moneda."""
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="1234.50")
    assert "$1,234.50" in cliente.get("/gastos").get_data(as_text=True)

    cliente.post("/perfil", data={
        "nombre": "Ana", "correo": "ana@ejemplo.com", "pais": "España",
        "ciudad": "", "moneda": "EUR", "zona_horaria": "Europe/Madrid"})
    pagina = cliente.get("/gastos").get_data(as_text=True)
    assert "1.234,50 €" in pagina
    assert "$1,234.50" not in pagina


def test_una_moneda_inventada_no_se_guarda(cliente):
    """RNF03: los valores de los desplegables se validan en el servidor,
    porque una peticion manipulada puede enviar cualquier cosa."""
    registrar(cliente)
    cliente.post("/perfil", data={
        "nombre": "Ana", "correo": "ana@ejemplo.com", "pais": "Atlántida",
        "ciudad": "", "moneda": "XXX", "zona_horaria": "Marte/Olympus"})
    usuario = Usuario.query.filter_by(correo="ana@ejemplo.com").first()
    assert usuario.moneda == localizacion.MONEDA_POR_DEFECTO
    assert usuario.zona_horaria == localizacion.ZONA_POR_DEFECTO
    assert usuario.pais == ""


def test_no_se_puede_tomar_el_correo_de_otra_cuenta(cliente):
    registrar(cliente)
    cliente.post("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    respuesta = cliente.post("/perfil", data={
        "nombre": "Luis", "correo": "ana@ejemplo.com", "pais": "", "ciudad": "",
        "moneda": "USD", "zona_horaria": "UTC"}, follow_redirects=True)
    assert "otra cuenta" in respuesta.get_data(as_text=True)
    assert Usuario.query.filter_by(correo="luis@ejemplo.com").first() is not None


# ---------------------------------------------------------------------
# Cambio de contrasena
# ---------------------------------------------------------------------
def test_cambiar_la_contrasena(cliente):
    registrar(cliente)
    cliente.post("/perfil/contrasena", data={
        "actual": "clave123", "nueva": "nuevaclave456",
        "confirmacion": "nuevaclave456"})
    cliente.post("/logout")
    respuesta = cliente.post("/login", data={"correo": "ana@ejemplo.com",
                                             "contrasena": "nuevaclave456"},
                             follow_redirects=True)
    assert "Registrar un gasto" in respuesta.get_data(as_text=True)


def test_sin_la_contrasena_actual_no_se_cambia(cliente):
    """Sin este requisito, quien encontrara una sesion abierta podria
    apoderarse de la cuenta."""
    registrar(cliente)
    respuesta = cliente.post("/perfil/contrasena", data={
        "actual": "equivocada", "nueva": "nuevaclave456",
        "confirmacion": "nuevaclave456"}, follow_redirects=True)
    assert "actual no es correcta" in respuesta.get_data(as_text=True)
    cliente.post("/logout")
    entrada = cliente.post("/login", data={"correo": "ana@ejemplo.com",
                                           "contrasena": "clave123"},
                           follow_redirects=True)
    assert "Registrar un gasto" in entrada.get_data(as_text=True)


def test_la_confirmacion_debe_coincidir(cliente):
    registrar(cliente)
    respuesta = cliente.post("/perfil/contrasena", data={
        "actual": "clave123", "nueva": "nuevaclave456",
        "confirmacion": "otra-distinta"}, follow_redirects=True)
    assert "no coincide" in respuesta.get_data(as_text=True)


def test_la_contrasena_nueva_debe_ser_larga(cliente):
    registrar(cliente)
    respuesta = cliente.post("/perfil/contrasena", data={
        "actual": "clave123", "nueva": "corta", "confirmacion": "corta"},
        follow_redirects=True)
    assert "al menos" in respuesta.get_data(as_text=True)


# ---------------------------------------------------------------------
# Baja de la cuenta
# ---------------------------------------------------------------------
def test_eliminar_la_cuenta_borra_todos_sus_datos(cliente):
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat())
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    cliente.post("/presupuesto", data={"monto_total": "900", "categoria_1": "200"})
    cliente.post("/perfil/eliminar", data={"contrasena": "clave123"},
                 follow_redirects=True)
    assert Usuario.query.filter_by(correo="ana@ejemplo.com").first() is None
    assert Gasto.query.count() == 0


def test_sin_la_contrasena_la_cuenta_no_se_elimina(cliente):
    """La accion es irreversible, por eso se confirma con la clave."""
    registrar(cliente)
    respuesta = cliente.post("/perfil/eliminar", data={"contrasena": "equivocada"},
                             follow_redirects=True)
    assert "no es correcta" in respuesta.get_data(as_text=True)
    assert Usuario.query.filter_by(correo="ana@ejemplo.com").first() is not None


def test_eliminar_la_cuenta_no_afecta_a_otros_usuarios(cliente):
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat())
    cliente.post("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="60")
    cliente.post("/perfil/eliminar", data={"contrasena": "clave456"},
                 follow_redirects=True)
    assert Usuario.query.filter_by(correo="ana@ejemplo.com").first() is not None
    assert Gasto.query.count() == 1

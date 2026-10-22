"""
Pruebas del presupuesto mensual y los avisos.
RF05: definicion del presupuesto total y por categoria.
RF10: aviso al superar el porcentaje definido.

Las pruebas se dividen en dos grupos: las del modulo presupuesto.py, que
no necesitan Flask ni base de datos, y las de las rutas, que recorren la
aplicacion completa como lo haria un usuario (pruebas de caja negra).
"""

from datetime import date

import presupuesto
from conftest import registrar, crear_gasto


# ---------------------------------------------------------------------
# Calculos del modulo (sin base de datos)
# ---------------------------------------------------------------------
def test_porcentaje_consumido():
    assert presupuesto.porcentaje_consumido(50, 200) == 25.0
    assert presupuesto.porcentaje_consumido(200, 200) == 100.0


def test_porcentaje_sin_presupuesto_es_cero():
    """Sin monto asignado no hay referencia contra la cual comparar."""
    assert presupuesto.porcentaje_consumido(80, 0) == 0.0


def test_clasificar_segun_el_umbral():
    assert presupuesto.clasificar(50, 100) == presupuesto.NORMAL
    assert presupuesto.clasificar(presupuesto.UMBRAL_AVISO, 100) == presupuesto.AVISO
    assert presupuesto.clasificar(99.9, 100) == presupuesto.AVISO
    assert presupuesto.clasificar(100, 100) == presupuesto.EXCEDIDO
    assert presupuesto.clasificar(140, 100) == presupuesto.EXCEDIDO
    assert presupuesto.clasificar(0, 0) == presupuesto.SIN_PRESUPUESTO


def test_comparar_calcula_totales_y_restante():
    c = presupuesto.comparar(1000, {"Alimentación": 400}, {"Alimentación": 150})
    assert c["total"]["gastado"] == 150.0
    assert c["total"]["restante"] == 850.0
    assert c["sin_asignar"] == 600.0
    assert c["sobreasignado"] is False
    assert c["categorias"][0]["porcentaje"] == 37.5


def test_comparar_incluye_categorias_sin_presupuesto():
    """Un gasto en una categoria no presupuestada debe aparecer igual,
    porque es justamente lo que el usuario no tenia previsto."""
    c = presupuesto.comparar(500, {"Transporte": 100}, {"Salud": 60})
    nombres = [l["categoria"] for l in c["categorias"]]
    assert "Salud" in nombres
    sin_presupuesto = [l for l in c["categorias"] if l["categoria"] == "Salud"][0]
    assert sin_presupuesto["estado"] == presupuesto.SIN_PRESUPUESTO


def test_comparar_detecta_sobreasignacion():
    c = presupuesto.comparar(300, {"Vivienda": 200, "Transporte": 200}, {})
    assert c["sobreasignado"] is True
    assert c["sin_asignar"] == -100.0


def test_la_barra_nunca_pasa_de_cien():
    c = presupuesto.comparar(100, {"Salud": 100}, {"Salud": 250})
    assert c["categorias"][0]["porcentaje"] == 250.0
    assert c["categorias"][0]["ancho"] == 100


def test_sin_presupuesto_no_hay_avisos():
    c = presupuesto.comparar(0, {}, {"Salud": 900})
    assert presupuesto.alertas(c) == []


def test_aviso_al_llegar_al_umbral():
    c = presupuesto.comparar(1000, {"Alimentación": 100}, {"Alimentación": 85})
    niveles = [a["nivel"] for a in presupuesto.alertas(c)]
    assert presupuesto.AVISO in niveles


def test_aviso_de_categoria_excedida():
    c = presupuesto.comparar(1000, {"Alimentación": 100}, {"Alimentación": 130})
    avisos = presupuesto.alertas(c)
    assert avisos[0]["nivel"] == presupuesto.EXCEDIDO
    assert "Alimentación" in avisos[0]["texto"]


def test_mes_desplazado_cambia_de_anio():
    assert presupuesto.mes_desplazado(1, 2026, -1) == (12, 2025)
    assert presupuesto.mes_desplazado(12, 2026, 1) == (1, 2027)


# ---------------------------------------------------------------------
# Rutas de la aplicacion (caja negra)
# ---------------------------------------------------------------------
def test_presupuesto_requiere_sesion(cliente):
    """RNF03: sin iniciar sesion la pantalla no es accesible."""
    respuesta = cliente.get("/presupuesto")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_guardar_y_mostrar_presupuesto(cliente):
    """RF05: el presupuesto guardado se ve al volver a la pantalla."""
    registrar(cliente)
    cliente.post("/presupuesto", data={"monto_total": "1200", "categoria_1": "400"})
    pagina = cliente.get("/presupuesto").get_data(as_text=True)
    assert "1200.00" in pagina
    assert "400.00" in pagina


def test_campo_en_blanco_elimina_la_asignacion(cliente):
    """Dejar una categoria vacia quita su presupuesto en lugar de
    guardarla en cero."""
    registrar(cliente)
    cliente.post("/presupuesto", data={"monto_total": "1000", "categoria_1": "300"})
    cliente.post("/presupuesto", data={"monto_total": "1000", "categoria_1": ""})
    pagina = cliente.get("/presupuesto").get_data(as_text=True)
    assert "300.00" not in pagina


def test_aviso_aparece_en_la_pantalla_de_gastos(cliente):
    """RF10: al pasar el umbral el aviso se muestra donde el usuario
    registra sus gastos."""
    registrar(cliente)
    cliente.post("/presupuesto", data={"monto_total": "100", "categoria_1": "100"})
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="95", categoria_id=1)
    pagina = cliente.get("/gastos").get_data(as_text=True)
    assert "aviso" in pagina
    assert "presupuestado" in pagina or "consumiste" in pagina


def test_sin_exceso_no_se_muestran_avisos(cliente):
    registrar(cliente)
    cliente.post("/presupuesto", data={"monto_total": "1000", "categoria_1": "500"})
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="20", categoria_id=1)
    pagina = cliente.get("/gastos").get_data(as_text=True)
    assert 'class="avisos"' not in pagina


def test_el_presupuesto_es_privado_de_cada_usuario(cliente):
    """RNF03: el presupuesto de un usuario no aparece en la cuenta de otro."""
    registrar(cliente)
    cliente.post("/presupuesto", data={"monto_total": "5000", "categoria_1": "999"})
    cliente.get("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    pagina = cliente.get("/presupuesto").get_data(as_text=True)
    assert "999.00" not in pagina
    assert "5000.00" not in pagina


def test_mes_invalido_en_la_url_no_rompe(cliente):
    """RNF01: una direccion manipulada cae en el mes en curso."""
    registrar(cliente)
    assert cliente.get("/presupuesto?mes=77&anio=abc").status_code == 200

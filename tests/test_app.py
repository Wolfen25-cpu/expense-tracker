"""
Pruebas de integracion de la aplicacion completa (caja negra).
Cada prueba recorre un requisito como lo haria un usuario: envia
formularios, sigue redirecciones y revisa lo que muestra la pagina.
"""

from datetime import date

from app import db, Usuario, Gasto
from conftest import registrar, crear_gasto


# ------------------------------------------------------------------- RF01
def test_rf01_registro_guarda_la_contrasena_hasheada(cliente):
    registrar(cliente, contrasena="secreta123")
    usuario = Usuario.query.filter_by(correo="ana@ejemplo.com").one()
    assert usuario.contrasena_hash != "secreta123"
    assert "secreta123" not in usuario.contrasena_hash


def test_rf01_login_correcto_e_incorrecto(cliente):
    registrar(cliente)
    cliente.post("/logout")
    malo = cliente.post("/login", data={"correo": "ana@ejemplo.com", "contrasena": "incorrecta"})
    assert "incorrectos" in malo.get_data(as_text=True)
    bueno = cliente.post("/login", data={"correo": "ana@ejemplo.com", "contrasena": "clave123"})
    assert bueno.status_code == 302


def test_rf01_correo_duplicado_es_rechazado(cliente):
    registrar(cliente)
    cliente.post("/logout")
    repetido = registrar(cliente, nombre="Otra")
    assert "ya está registrado" in repetido.get_data(as_text=True)
    assert Usuario.query.count() == 1


def test_rf01_rutas_protegidas_redirigen_al_login(cliente):
    for ruta in ("/gastos", "/reportes", "/reportes/exportar.csv"):
        respuesta = cliente.get(ruta)
        assert respuesta.status_code == 302 and "/login" in respuesta.headers["Location"]


# ------------------------------------------------------------------- RF02
def test_rf02_registrar_gasto_aparece_en_el_historial(cliente):
    registrar(cliente)
    crear_gasto(cliente, monto="42.75", descripcion="Supermercado")
    pagina = cliente.get("/gastos").get_data(as_text=True)
    assert "Supermercado" in pagina and "$42.75" in pagina


# ------------------------------------------------------------------- RF03
def test_rf03_editar_gasto(cliente):
    registrar(cliente)
    crear_gasto(cliente, monto="10.00")
    gasto = Gasto.query.one()
    cliente.post(f"/gastos/{gasto.id}/editar", data={
        "fecha": "2026-10-16", "monto": "99.99", "categoria_id": 2,
        "descripcion": "Corregido", "metodo_pago": "Tarjeta de débito",
    })
    db.session.refresh(gasto)
    assert gasto.monto == 99.99 and gasto.descripcion == "Corregido"


def test_rf03_eliminar_gasto(cliente):
    registrar(cliente)
    crear_gasto(cliente)
    gasto_id = Gasto.query.one().id
    cliente.post(f"/gastos/{gasto_id}/eliminar")
    assert Gasto.query.count() == 0


# ------------------------------------------------------- RNF03: aislamiento
def test_rnf03_un_usuario_no_puede_editar_ni_eliminar_gastos_ajenos(cliente):
    registrar(cliente, nombre="Ana", correo="ana@ejemplo.com")
    crear_gasto(cliente, monto="10.00")
    gasto_id = Gasto.query.one().id
    cliente.post("/logout")

    registrar(cliente, nombre="Beto", correo="beto@ejemplo.com")
    assert cliente.get(f"/gastos/{gasto_id}/editar").status_code == 404
    assert cliente.post(f"/gastos/{gasto_id}/eliminar").status_code == 404
    assert Gasto.query.count() == 1


def test_rnf03_los_reportes_solo_incluyen_gastos_propios(cliente):
    registrar(cliente, nombre="Ana", correo="ana@ejemplo.com")
    crear_gasto(cliente, fecha="2026-10-15", monto="500.00", descripcion="Solo de Ana")
    cliente.post("/logout")

    registrar(cliente, nombre="Beto", correo="beto@ejemplo.com")
    crear_gasto(cliente, fecha="2026-10-15", monto="7.00", descripcion="Solo de Beto")
    pagina = cliente.get("/reportes?periodo=mensual&fecha=2026-10-15").get_data(as_text=True)
    assert "$7.00" in pagina and "$500.00" not in pagina
    csv = cliente.get("/reportes/exportar.csv?periodo=mensual&fecha=2026-10-15").get_data(as_text=True)
    assert "Solo de Beto" in csv and "Solo de Ana" not in csv


# ------------------------------------------------------------- RF06 y RF07
def test_rf06_reporte_mensual_muestra_totales_y_categorias(cliente):
    registrar(cliente)
    crear_gasto(cliente, fecha="2026-10-03", monto="100.00", categoria_id=1)
    crear_gasto(cliente, fecha="2026-10-20", monto="50.00", categoria_id=2)
    crear_gasto(cliente, fecha="2026-09-30", monto="999.00", categoria_id=1)   # otro mes
    pagina = cliente.get("/reportes?periodo=mensual&fecha=2026-10-15").get_data(as_text=True)
    assert "Octubre 2026" in pagina
    assert "$150.00" in pagina                 # total del mes
    assert "$999.00" not in pagina             # no se cuela el mes anterior
    assert "Alimentación" in pagina and "Transporte" in pagina


def test_rf06_los_cuatro_periodos_responden(cliente):
    registrar(cliente)
    crear_gasto(cliente, fecha="2026-10-15")
    for periodo in ("diario", "semanal", "mensual", "anual"):
        assert cliente.get(f"/reportes?periodo={periodo}&fecha=2026-10-15").status_code == 200


def test_rf06_parametros_invalidos_no_rompen_la_pagina(cliente):
    registrar(cliente)
    assert cliente.get("/reportes?periodo=hackeo&fecha=no-es-fecha").status_code == 200


def test_rf06_periodo_sin_gastos_muestra_mensaje(cliente):
    registrar(cliente)
    pagina = cliente.get("/reportes?periodo=mensual&fecha=2026-10-15").get_data(as_text=True)
    assert "No hay gastos registrados en este periodo" in pagina


def test_rf07_la_pagina_incluye_las_dos_graficas(cliente):
    registrar(cliente)
    crear_gasto(cliente, fecha="2026-10-15", monto="20.00")
    pagina = cliente.get("/reportes?periodo=mensual&fecha=2026-10-15").get_data(as_text=True)
    assert pagina.count("data:image/png;base64,") == 2


# ------------------------------------------------------------------- RF09
def test_rf09_exportar_csv(cliente):
    registrar(cliente)
    crear_gasto(cliente, fecha="2026-10-15", monto="12.34", descripcion="Almuerzo")
    respuesta = cliente.get("/reportes/exportar.csv?periodo=mensual&fecha=2026-10-15")
    assert respuesta.mimetype == "text/csv"
    assert "attachment" in respuesta.headers["Content-Disposition"]
    texto = respuesta.get_data(as_text=True)
    assert "Almuerzo" in texto and "12.34" in texto

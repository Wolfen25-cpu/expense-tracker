"""
Pruebas de las recomendaciones de ahorro (RF08).

Ninguna prueba llama al servicio externo: la funcion que habla con el
modelo se sustituye por una falsa. Las pruebas deben ser rapidas,
repetibles y no depender de internet ni consumir la cuota de la cuenta.
"""

from datetime import date

import pytest

import recomendaciones
from conftest import registrar, crear_gasto


class GastoFalso:
    """Imita lo justo de un Gasto del modelo para probar el modulo sin
    base de datos."""

    class _Categoria:
        def __init__(self, nombre):
            self.nombre = nombre

    def __init__(self, categoria, monto, fecha=None, descripcion=""):
        self.categoria = self._Categoria(categoria)
        self.monto = monto
        self.fecha = fecha or date.today()
        self.descripcion = descripcion


@pytest.fixture
def sin_red(monkeypatch):
    """Evita cualquier llamada real al servicio de IA durante las
    pruebas de las rutas: el nivel generativo devuelve vacio y el
    sistema cae al nivel de reglas."""
    monkeypatch.setattr(recomendaciones, "recomendar_con_ia", lambda resumen: [])
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")


def resumen_de(gastado_mes, anterior=None, presupuesto_lineas=None, recurrentes=None):
    """Arma un resumen minimo para probar las reglas sin pasar por la
    base de datos."""
    total = sum(gastado_mes.values())
    anterior = anterior or {}
    categorias = []
    for nombre, monto in gastado_mes.items():
        previo = anterior.get(nombre, 0)
        categorias.append({
            "categoria": nombre,
            "total": monto,
            "porcentaje": round(monto / total * 100, 1) if total else 0,
            "anterior": previo,
            "variacion": round((monto - previo) / previo * 100, 1) if previo else None,
        })
    return {
        "periodo": "Octubre 2026",
        "total": total,
        "total_anterior": sum(anterior.values()),
        "cantidad_categorias": len(categorias),
        "categorias": categorias,
        "presupuesto": presupuesto_lineas or [],
        "presupuesto_total": 0,
        "recurrentes": recurrentes or [],
    }


# ---------------------------------------------------------------------
# Nivel analitico
# ---------------------------------------------------------------------
def test_detectar_recurrentes_necesita_meses_distintos():
    """Una suscripcion es un gasto que reaparece mes tras mes."""
    gastos = [
        GastoFalso("Mensualidades", 45.0, date(2026, 9, 5), "Telefono"),
        GastoFalso("Mensualidades", 45.0, date(2026, 10, 5), "Telefono"),
        GastoFalso("Alimentación", 12.5, date(2026, 10, 6), "Cafe"),
    ]
    recurrentes = recomendaciones.detectar_recurrentes(gastos)
    assert len(recurrentes) == 1
    assert recurrentes[0]["categoria"] == "Mensualidades"
    assert recurrentes[0]["veces"] == 2


def test_dos_gastos_iguales_del_mismo_mes_no_son_recurrentes():
    """Dos compras del mismo monto en octubre son dos compras, no una
    suscripcion mensual."""
    gastos = [
        GastoFalso("Alimentación", 30.0, date(2026, 10, 3), "Supermercado"),
        GastoFalso("Alimentación", 30.0, date(2026, 10, 18), "Supermercado"),
    ]
    assert recomendaciones.detectar_recurrentes(gastos) == []


def test_dos_servicios_distintos_del_mismo_monto_no_se_mezclan():
    """El telefono y un programa pueden costar $20 cada uno. Si se
    agruparan solo por monto, el sistema reportaria una sola suscripcion
    de $20 repetida, que es un dato falso."""
    gastos = [
        GastoFalso("Mensualidades", 20.0, date(2026, 10, 2), "Telefono"),
        GastoFalso("Mensualidades", 20.0, date(2026, 10, 2), "Programa"),
    ]
    assert recomendaciones.detectar_recurrentes(gastos) == []

    # Cada uno por separado si es recurrente cuando se repite el mes siguiente
    gastos += [
        GastoFalso("Mensualidades", 20.0, date(2026, 11, 2), "Telefono"),
        GastoFalso("Mensualidades", 20.0, date(2026, 11, 2), "Programa"),
    ]
    recurrentes = recomendaciones.detectar_recurrentes(gastos)
    assert len(recurrentes) == 2


def test_el_resultado_no_incluye_la_descripcion():
    """RNF06: la descripcion sirve para agrupar dentro del sistema, pero
    no sale del equipo del usuario."""
    gastos = [
        GastoFalso("Mensualidades", 20.0, date(2026, 10, 2), "Telefono personal"),
        GastoFalso("Mensualidades", 20.0, date(2026, 11, 2), "Telefono personal"),
    ]
    recurrentes = recomendaciones.detectar_recurrentes(gastos)
    assert "personal" not in str(recurrentes).lower()


def test_detectar_recurrentes_sin_gastos():
    assert recomendaciones.detectar_recurrentes([]) == []


def test_el_resumen_no_lleva_datos_personales():
    """RNF06: al servicio externo solo viajan categorias y cifras, nunca
    descripciones ni datos del usuario."""
    comparacion = {"categorias": [], "total": {"asignado": 0.0}}
    resumen = recomendaciones.construir_resumen(
        "Octubre 2026", {"Salud": 80.0}, {}, comparacion, [])
    texto = str(resumen).lower()
    assert "descripcion" not in texto
    assert "correo" not in texto
    assert resumen["categorias"][0]["categoria"] == "Salud"


def test_el_resumen_calcula_la_variacion_mensual():
    comparacion = {"categorias": [], "total": {"asignado": 0.0}}
    resumen = recomendaciones.construir_resumen(
        "Octubre 2026", {"Transporte": 150.0}, {"Transporte": 100.0}, comparacion, [])
    assert resumen["categorias"][0]["variacion"] == 50.0


# ---------------------------------------------------------------------
# Reglas de negocio
# ---------------------------------------------------------------------
def test_regla_de_presupuesto_excedido():
    resumen = resumen_de(
        {"Alimentación": 260.0},
        presupuesto_lineas=[{"categoria": "Alimentación", "asignado": 200.0,
                             "gastado": 260.0, "exceso": 60.0, "porcentaje": 130.0}],
    )
    sugerencias = recomendaciones.recomendar_por_reglas(resumen)
    assert any(s["ahorro_estimado"] == 60.0 for s in sugerencias)


def test_regla_de_crecimiento_respecto_al_mes_anterior():
    resumen = resumen_de({"Transporte": 150.0}, anterior={"Transporte": 100.0})
    textos = " ".join(s["texto"] for s in recomendaciones.recomendar_por_reglas(resumen))
    assert "Transporte" in textos


def test_regla_de_gasto_recurrente():
    resumen = resumen_de(
        {"Mensualidades": 90.0},
        recurrentes=[{"categoria": "Mensualidades", "monto": 45.0, "veces": 2}],
    )
    textos = " ".join(s["texto"] for s in recomendaciones.recomendar_por_reglas(resumen))
    assert "recurrente" in textos


def test_un_gasto_fijo_esencial_no_se_recomienda_cancelar():
    """El alquiler se repite todos los meses igual que una suscripcion,
    pero recomendar cancelarlo seria absurdo. Para los gastos esenciales
    la via es renegociar, y el ahorro estimado es una rebaja parcial, no
    el monto completo."""
    resumen = resumen_de(
        {"Vivienda": 650.0},
        recurrentes=[{"categoria": "Vivienda", "monto": 650.0, "veces": 3}],
    )
    sugerencias = recomendaciones.recomendar_por_reglas(resumen)
    textos = " ".join(s["texto"] for s in sugerencias)
    assert "cancelar" not in textos.lower()
    assert "renegociarlo" in textos
    assert all(s["ahorro_estimado"] < 650.0 for s in sugerencias)


def test_una_categoria_desconocida_se_trata_como_fija():
    """Ante una categoria personalizada que el sistema no conoce, la
    opcion prudente es no sugerir cancelarla."""
    assert recomendaciones.clasificar_recurrente("Jardinería") == recomendaciones.TIPO_FIJO
    assert recomendaciones.clasificar_recurrente("Mensualidades") == recomendaciones.TIPO_CANCELABLE


def test_sin_problemas_devuelve_un_mensaje_positivo():
    """Nunca se devuelve una lista vacia: la pantalla siempre dice algo."""
    sugerencias = recomendaciones.recomendar_por_reglas(resumen_de({"Salud": 10.0}))
    assert len(sugerencias) == 1
    assert sugerencias[0]["ahorro_estimado"] == 0.0


def test_se_devuelven_como_maximo_cinco():
    resumen = resumen_de(
        {f"Categoria {i}": 100.0 for i in range(8)},
        anterior={f"Categoria {i}": 10.0 for i in range(8)},
    )
    assert len(recomendaciones.recomendar_por_reglas(resumen)) <= recomendaciones.MAXIMO_RECOMENDACIONES


# ---------------------------------------------------------------------
# Interpretacion de la respuesta del modelo
# ---------------------------------------------------------------------
def test_interpretar_respuesta_valida():
    contenido = '{"recomendaciones": [{"texto": "Reduce cafe", "ahorro_estimado": 25.5}]}'
    assert recomendaciones.interpretar_respuesta(contenido) == [
        {"texto": "Reduce cafe", "ahorro_estimado": 25.5}]


def test_interpretar_respuesta_dentro_de_un_bloque_de_codigo():
    contenido = '```json\n{"recomendaciones": [{"texto": "Ahorra", "ahorro_estimado": 10}]}\n```'
    assert recomendaciones.interpretar_respuesta(contenido)[0]["ahorro_estimado"] == 10.0


def test_interpretar_respuesta_descarta_items_invalidos():
    """La respuesta de un modelo no es confiable: se valida cada campo."""
    contenido = ('{"recomendaciones": [{"texto": "", "ahorro_estimado": 5}, '
                 '{"texto": "Valida", "ahorro_estimado": "no es numero"}]}')
    limpias = recomendaciones.interpretar_respuesta(contenido)
    assert limpias == [{"texto": "Valida", "ahorro_estimado": 0.0}]


# ---------------------------------------------------------------------
# Cascada entre los dos niveles
# ---------------------------------------------------------------------
def test_sin_clave_se_usan_las_reglas(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _, origen, error = recomendaciones.generar(resumen_de({"Salud": 10.0}))
    assert origen == recomendaciones.ORIGEN_REGLAS
    assert "clave" in error


def test_si_el_servicio_falla_se_usan_las_reglas(monkeypatch):
    """El fallo de un servicio externo nunca debe dejar al usuario sin
    recomendaciones ni tumbar la pantalla."""
    def explotar(resumen):
        raise ConnectionError("sin conexion")

    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(recomendaciones, "recomendar_con_ia", explotar)
    sugerencias, origen, error = recomendaciones.generar(resumen_de({"Salud": 10.0}))
    assert sugerencias
    assert origen == recomendaciones.ORIGEN_REGLAS
    assert "ConnectionError" in error


def test_si_el_servicio_responde_se_usa_la_ia(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(recomendaciones, "recomendar_con_ia",
                        lambda resumen: [{"texto": "Consejo", "ahorro_estimado": 30.0}])
    sugerencias, origen, error = recomendaciones.generar(resumen_de({"Salud": 10.0}))
    assert origen == recomendaciones.ORIGEN_IA
    assert error is None
    assert sugerencias[0]["texto"] == "Consejo"


# ---------------------------------------------------------------------
# Rutas de la aplicacion (caja negra)
# ---------------------------------------------------------------------
def test_recomendaciones_requieren_sesion(cliente):
    respuesta = cliente.get("/recomendaciones")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_generar_guarda_el_historial(cliente, sin_red):
    """RF08: al generar, las recomendaciones quedan guardadas y se ven."""
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="80", categoria_id=1)
    cliente.post("/recomendaciones/generar", follow_redirects=True)
    pagina = cliente.get("/recomendaciones").get_data(as_text=True)
    assert "Reglas del sistema" in pagina


def test_marcar_como_aplicada(cliente, sin_red):
    """El historial de aplicadas es el dato con el que se mide el cambio
    de conducta durante la validacion."""
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="80", categoria_id=1)
    cliente.post("/recomendaciones/generar", follow_redirects=True)
    cliente.post("/recomendaciones/1/aplicar", follow_redirects=True)
    pagina = cliente.get("/recomendaciones").get_data(as_text=True)
    assert "Marcada como aplicada" in pagina


def test_las_recomendaciones_son_privadas(cliente, sin_red):
    """RNF03: el historial de un usuario no aparece en otra cuenta."""
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="80", categoria_id=1)
    cliente.post("/recomendaciones/generar", follow_redirects=True)
    cliente.post("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    pagina = cliente.get("/recomendaciones").get_data(as_text=True)
    assert "Todavía no has generado recomendaciones" in pagina


def test_no_se_puede_aplicar_la_recomendacion_de_otro(cliente, sin_red):
    registrar(cliente)
    crear_gasto(cliente, fecha=date.today().isoformat(), monto="80", categoria_id=1)
    cliente.post("/recomendaciones/generar", follow_redirects=True)
    cliente.post("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    assert cliente.post("/recomendaciones/1/aplicar").status_code == 404


def test_la_concentracion_solo_aplica_con_varias_categorias():
    """Con una sola categoria el gasto se concentra al 100% por pura
    aritmetica, asi que el aviso no aportaria nada. La regla exige
    variedad para tener sentido."""
    una_sola = recomendaciones.recomendar_por_reglas(resumen_de({"Salud": 500.0}))
    assert all("concentra" not in s["texto"] for s in una_sola)

    varias = recomendaciones.recomendar_por_reglas(
        resumen_de({"Vivienda": 500.0, "Salud": 50.0, "Transporte": 40.0}))
    assert any("concentra" in s["texto"] for s in varias)

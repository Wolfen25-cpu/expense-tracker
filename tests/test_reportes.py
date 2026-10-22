"""
Pruebas unitarias del modulo reportes.py (RF06, RF07, RF09).
Se prueban los calculos con datos conocidos: el resultado esperado se
calcula a mano y se compara con lo que devuelve el sistema.
"""

from datetime import date
from types import SimpleNamespace

import pytest

import reportes


def gasto(fecha, monto, categoria="Alimentación", descripcion="", metodo="Efectivo"):
    """Gasto de prueba con la misma forma que el modelo Gasto."""
    return SimpleNamespace(
        fecha=fecha, monto=monto, descripcion=descripcion, metodo_pago=metodo,
        categoria=SimpleNamespace(nombre=categoria),
    )


# ---------------------------------------------------------------- periodos
def test_rango_diario():
    assert reportes.rango_periodo("diario", date(2026, 10, 21)) == (date(2026, 10, 21), date(2026, 10, 21))


def test_rango_semanal_va_de_lunes_a_domingo():
    # El 21 de octubre de 2026 es miercoles
    assert reportes.rango_periodo("semanal", date(2026, 10, 21)) == (date(2026, 10, 19), date(2026, 10, 25))


def test_rango_mensual_octubre_tiene_31_dias():
    assert reportes.rango_periodo("mensual", date(2026, 10, 21)) == (date(2026, 10, 1), date(2026, 10, 31))


def test_rango_mensual_febrero_bisiesto():
    assert reportes.rango_periodo("mensual", date(2028, 2, 10))[1] == date(2028, 2, 29)


def test_rango_mensual_diciembre_cierra_el_anio():
    assert reportes.rango_periodo("mensual", date(2026, 12, 5)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_rango_anual():
    assert reportes.rango_periodo("anual", date(2026, 6, 3)) == (date(2026, 1, 1), date(2026, 12, 31))


def test_periodo_invalido_lanza_error():
    with pytest.raises(ValueError):
        reportes.rango_periodo("quincenal", date(2026, 1, 1))


def test_desplazar_mes_cruza_de_anio():
    assert reportes.desplazar("mensual", date(2026, 1, 15), -1) == date(2025, 12, 1)
    assert reportes.desplazar("mensual", date(2026, 12, 15), 1) == date(2027, 1, 1)


def test_desplazar_semana_y_dia():
    assert reportes.desplazar("semanal", date(2026, 10, 21), 1) == date(2026, 10, 28)
    assert reportes.desplazar("diario", date(2026, 3, 1), -1) == date(2026, 2, 28)


def test_reporte_diario_consulta_ventana_de_7_dias():
    desde, hasta = reportes.rango_consulta("diario", date(2026, 10, 21))
    assert (desde, hasta) == (date(2026, 10, 15), date(2026, 10, 21))


# ------------------------------------------------------------------ calculos
def test_resumen_con_datos_conocidos():
    datos = [gasto(date(2026, 10, 1), 10.0), gasto(date(2026, 10, 2), 30.0), gasto(date(2026, 10, 3), 20.0)]
    r = reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))["resumen"]
    assert r == {"total": 60.0, "cantidad": 3, "promedio": 20.0, "mayor": 30.0}


def test_resumen_sin_gastos_no_falla():
    r = reportes.calcular_reporte([], "mensual", date(2026, 10, 15))
    assert r["resumen"] == {"total": 0.0, "cantidad": 0, "promedio": 0.0, "mayor": 0.0}
    assert r["categorias"] == []


def test_totales_por_categoria_ordenados_y_porcentajes():
    datos = [
        gasto(date(2026, 10, 1), 75.0, "Vivienda"),
        gasto(date(2026, 10, 2), 15.0, "Transporte"),
        gasto(date(2026, 10, 3), 10.0, "Transporte"),
    ]
    cats = reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))["categorias"]
    assert [c["categoria"] for c in cats] == ["Vivienda", "Transporte"]
    assert cats[0] == {"categoria": "Vivienda", "total": 75.0, "porcentaje": 75.0}
    assert cats[1] == {"categoria": "Transporte", "total": 25.0, "porcentaje": 25.0}
    assert sum(c["porcentaje"] for c in cats) == pytest.approx(100.0)


def test_el_periodo_excluye_gastos_de_otros_meses():
    datos = [gasto(date(2026, 9, 30), 100.0), gasto(date(2026, 10, 1), 5.0), gasto(date(2026, 11, 1), 200.0)]
    assert reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))["resumen"]["total"] == 5.0


def test_evolucion_mensual_rellena_dias_sin_gasto_con_cero():
    datos = [gasto(date(2026, 10, 2), 10.0), gasto(date(2026, 10, 2), 5.0), gasto(date(2026, 10, 31), 7.0)]
    ev = reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))["evolucion"]
    assert len(ev["valores"]) == 31
    assert ev["valores"][1] == 15.0      # dia 2: dos gastos sumados
    assert ev["valores"][2] == 0.0       # dia 3: sin gastos
    assert ev["valores"][30] == 7.0      # dia 31


def test_evolucion_anual_tiene_12_meses():
    datos = [gasto(date(2026, 1, 10), 40.0), gasto(date(2026, 12, 5), 60.0)]
    ev = reportes.calcular_reporte(datos, "anual", date(2026, 6, 1))["evolucion"]
    assert len(ev["valores"]) == 12
    assert ev["valores"][0] == 40.0 and ev["valores"][11] == 60.0
    assert sum(ev["valores"]) == 100.0


def test_evolucion_diaria_usa_ultimos_7_dias_pero_el_total_es_solo_del_dia():
    datos = [gasto(date(2026, 10, 16), 9.0), gasto(date(2026, 10, 21), 4.0)]
    r = reportes.calcular_reporte(datos, "diario", date(2026, 10, 21))
    assert r["resumen"]["total"] == 4.0
    assert len(r["evolucion"]["valores"]) == 7
    assert r["evolucion"]["valores"][0] == 0.0 and r["evolucion"]["valores"][1] == 9.0


# -------------------------------------------------------------------- graficas
def test_graficas_devuelven_png_en_base64():
    import base64
    datos = [gasto(date(2026, 10, 1), 10.0, "Salud"), gasto(date(2026, 10, 2), 20.0, "Otros")]
    r = reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))
    for imagen in (reportes.grafica_distribucion(r["categorias"]), reportes.grafica_evolucion(r["evolucion"])):
        assert base64.b64decode(imagen)[:8] == b"\x89PNG\r\n\x1a\n"


def test_graficas_sin_datos_devuelven_none():
    r = reportes.calcular_reporte([], "mensual", date(2026, 10, 15))
    assert reportes.grafica_distribucion(r["categorias"]) is None
    assert reportes.grafica_evolucion(r["evolucion"]) is None


# ------------------------------------------------------------------ exportacion
def test_csv_tiene_encabezado_y_filas_ordenadas():
    datos = [gasto(date(2026, 10, 5), 12.5, "Salud", "Farmacia"), gasto(date(2026, 10, 1), 3.0, "Otros", "Cafe")]
    csv_texto = reportes.exportar_csv(reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))["df"])
    lineas = csv_texto.strip().splitlines()
    assert lineas[0] == "Fecha,Categoria,Descripcion,Monto,Metodo de pago"
    assert lineas[1].startswith("2026-10-01,Otros,Cafe,3.00")
    assert lineas[2].startswith("2026-10-05,Salud,Farmacia,12.50")


def test_csv_neutraliza_formulas_de_excel():
    datos = [gasto(date(2026, 10, 1), 1.0, descripcion="=HYPERLINK(\"http://malo\")")]
    csv_texto = reportes.exportar_csv(reportes.calcular_reporte(datos, "mensual", date(2026, 10, 15))["df"])
    assert "'=HYPERLINK" in csv_texto

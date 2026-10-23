"""
Modulo de reportes del Rastreador de Gastos.
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Pertenece a la capa de logica de negocio (seccion 5.2.1 de la Tarea #2).
Concentra los calculos con pandas y las graficas con matplotlib, de modo
que app.py solo coordina y las funciones se pueden probar sin Flask.

Requisitos que soporta:
  RF06  reportes diarios, semanales, mensuales y anuales con totales
        por categoria (la comparacion contra el presupuesto queda para
        la iteracion de RF05).
  RF07  graficas de distribucion por categoria y de evolucion en el tiempo.
  RF09  exportacion del reporte en formato CSV.
  RNF02 rendimiento: los calculos se hacen con operaciones vectorizadas
        de pandas, sin recorrer los gastos uno por uno.
  RNF05 mantenibilidad: modulo independiente, funciones cortas y con
        una sola responsabilidad.
"""

import base64
import csv
import io
from datetime import date, timedelta

import pandas as pd
from matplotlib.figure import Figure

# ---------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------
PERIODOS = {
    "diario": "Diario",
    "semanal": "Semanal",
    "mensual": "Mensual",
    "anual": "Anual",
}

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago",
                "Sep", "Oct", "Nov", "Dic"]

COLUMNAS = ["fecha", "monto", "categoria", "descripcion", "metodo_pago"]

# Paleta de las graficas. El primer color es el acento de estilos.css para
# que las graficas se vean integradas con el resto de la interfaz (RNF01).
PALETA = ["#2f6f6b", "#d98b3a", "#4a7fb0", "#b3453c",
          "#8a6fb0", "#6aa84f", "#c9a227", "#7a8794"]


# ---------------------------------------------------------------------
# Calculo de periodos (RF06)
# ---------------------------------------------------------------------
def rango_periodo(periodo, referencia):
    """Devuelve (inicio, fin), ambos inclusivos, del periodo que contiene
    la fecha de referencia. La semana va de lunes a domingo."""
    if periodo == "diario":
        return referencia, referencia
    if periodo == "semanal":
        inicio = referencia - timedelta(days=referencia.weekday())
        return inicio, inicio + timedelta(days=6)
    if periodo == "mensual":
        inicio = referencia.replace(day=1)
        siguiente = (inicio + timedelta(days=32)).replace(day=1)
        return inicio, siguiente - timedelta(days=1)
    if periodo == "anual":
        return date(referencia.year, 1, 1), date(referencia.year, 12, 31)
    raise ValueError(f"Periodo no valido: {periodo}")


def rango_evolucion(periodo, inicio, fin):
    """Rango que muestra la grafica de evolucion. Un solo dia no forma una
    linea, por eso el reporte diario muestra los ultimos 7 dias. En los
    demas periodos coincide con el propio periodo."""
    if periodo == "diario":
        return fin - timedelta(days=6), fin
    return inicio, fin


def rango_consulta(periodo, referencia):
    """Rango de fechas que debe leerse de la base de datos para armar el
    reporte completo (periodo mas ventana de la grafica de evolucion)."""
    inicio, fin = rango_periodo(periodo, referencia)
    desde, _ = rango_evolucion(periodo, inicio, fin)
    return desde, fin


def desplazar(periodo, referencia, pasos):
    """Mueve la referencia hacia atras (pasos negativos) o adelante para
    los botones Anterior y Siguiente de la pantalla de reportes."""
    if periodo == "diario":
        return referencia + timedelta(days=pasos)
    if periodo == "semanal":
        return referencia + timedelta(weeks=pasos)
    if periodo == "mensual":
        indice = referencia.year * 12 + (referencia.month - 1) + pasos
        return date(indice // 12, indice % 12 + 1, 1)
    if periodo == "anual":
        return date(referencia.year + pasos, 1, 1)
    raise ValueError(f"Periodo no valido: {periodo}")


def etiqueta_periodo(periodo, inicio, fin):
    """Texto legible del periodo para el encabezado del reporte."""
    if periodo == "diario":
        return inicio.strftime("%d/%m/%Y")
    if periodo == "semanal":
        return f"Semana del {inicio.strftime('%d/%m/%Y')} al {fin.strftime('%d/%m/%Y')}"
    if periodo == "mensual":
        return f"{MESES[inicio.month - 1]} {inicio.year}"
    return str(inicio.year)


# ---------------------------------------------------------------------
# Calculos con pandas (RF06, RNF02)
# ---------------------------------------------------------------------
def construir_dataframe(gastos):
    """Convierte los gastos (objetos del modelo Gasto) en una tabla de
    pandas. Si no hay gastos devuelve una tabla vacia con las mismas
    columnas, de modo que el resto de las funciones no necesitan casos
    especiales."""
    filas = [
        {
            "fecha": g.fecha,
            "monto": float(g.monto),
            "categoria": g.categoria.nombre,
            "descripcion": g.descripcion or "",
            "metodo_pago": g.metodo_pago or "",
        }
        for g in gastos
    ]
    df = pd.DataFrame(filas, columns=COLUMNAS)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def filtrar(df, inicio, fin):
    """Deja solo los gastos cuya fecha cae dentro de [inicio, fin]."""
    mascara = (df["fecha"] >= pd.Timestamp(inicio)) & (df["fecha"] <= pd.Timestamp(fin))
    return df[mascara]


def resumen(df):
    """Indicadores generales del periodo: total, cantidad, promedio por
    gasto y gasto mayor."""
    cantidad = int(len(df))
    total = round(float(df["monto"].sum()), 2)
    return {
        "total": total,
        "cantidad": cantidad,
        "promedio": round(total / cantidad, 2) if cantidad else 0.0,
        "mayor": round(float(df["monto"].max()), 2) if cantidad else 0.0,
    }


def totales_por_categoria(df):
    """Total y porcentaje de cada categoria, de mayor a menor (RF06)."""
    if df.empty:
        return []
    sumas = df.groupby("categoria")["monto"].sum().sort_values(ascending=False)
    gran_total = float(sumas.sum())
    return [
        {
            "categoria": nombre,
            "total": round(float(valor), 2),
            "porcentaje": round(float(valor) / gran_total * 100, 1) if gran_total else 0.0,
        }
        for nombre, valor in sumas.items()
    ]


def evolucion(df, periodo, desde, hasta):
    """Serie de gasto total a lo largo del tiempo (RF07). El reporte anual
    se agrupa por mes y los demas por dia. Los dias o meses sin gastos se
    rellenan con cero para que la linea no tenga huecos."""
    if periodo == "anual":
        por_mes = df.groupby(df["fecha"].dt.month)["monto"].sum()
        por_mes = por_mes.reindex(range(1, 13), fill_value=0)
        return {
            "etiquetas": MESES_CORTOS,
            "valores": [round(float(v), 2) for v in por_mes.values],
        }
    por_dia = df.groupby(df["fecha"].dt.normalize())["monto"].sum()
    por_dia = por_dia.reindex(pd.date_range(desde, hasta), fill_value=0)
    return {
        "etiquetas": [d.strftime("%d/%m") for d in por_dia.index],
        "valores": [round(float(v), 2) for v in por_dia.values],
    }


def calcular_reporte(gastos, periodo, referencia):
    """Punto de entrada del modulo: recibe los gastos leidos de la base de
    datos (ya filtrados por usuario y por rango_consulta) y devuelve todo
    lo que necesita la pantalla y la exportacion."""
    inicio, fin = rango_periodo(periodo, referencia)
    desde, hasta = rango_evolucion(periodo, inicio, fin)
    df_ventana = construir_dataframe(gastos)
    df = filtrar(df_ventana, inicio, fin)
    return {
        "periodo": periodo,
        "etiqueta": etiqueta_periodo(periodo, inicio, fin),
        "inicio": inicio,
        "fin": fin,
        "resumen": resumen(df),
        "categorias": totales_por_categoria(df),
        "evolucion": evolucion(df_ventana, periodo, desde, hasta),
        "df": df,
    }


# ---------------------------------------------------------------------
# Graficas (RF07)
# Se usa Figure directamente y no pyplot: pyplot guarda estado global y
# no es seguro cuando Flask atiende varias peticiones a la vez.
# Cada grafica se devuelve como texto base64 para incrustarla en el HTML
# sin crear archivos temporales en el disco.
# ---------------------------------------------------------------------
def _a_base64(figura):
    memoria = io.BytesIO()
    figura.savefig(memoria, format="png", dpi=110, bbox_inches="tight")
    return base64.b64encode(memoria.getvalue()).decode("ascii")


def grafica_distribucion(categorias):
    """Grafica circular con la distribucion del gasto por categoria.
    Devuelve None si no hay datos que graficar."""
    if not categorias:
        return None
    figura = Figure(figsize=(5.2, 3.8))
    eje = figura.subplots()
    colores = [PALETA[i % len(PALETA)] for i in range(len(categorias))]
    eje.pie(
        [c["total"] for c in categorias],
        colors=colores,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.45, "edgecolor": "white"},
    )
    eje.legend(
        [f"{c['categoria']} ({c['porcentaje']}%)" for c in categorias],
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        fontsize=9,
    )
    eje.set_aspect("equal")
    return _a_base64(figura)


def grafica_evolucion(serie, simbolo="$"):
    """Grafica de linea con el gasto total a lo largo del periodo.
    Devuelve None si todos los valores son cero."""
    if not any(serie["valores"]):
        return None
    figura = Figure(figsize=(6.4, 3.4))
    eje = figura.subplots()
    posiciones = list(range(len(serie["valores"])))
    eje.plot(posiciones, serie["valores"], color=PALETA[0], linewidth=2, marker="o", markersize=4)
    eje.fill_between(posiciones, serie["valores"], color=PALETA[0], alpha=0.12)
    # Con muchos puntos (un mes) se muestran solo algunas etiquetas
    salto = max(1, len(posiciones) // 8)
    eje.set_xticks(posiciones[::salto])
    eje.set_xticklabels(serie["etiquetas"][::salto], fontsize=8)
    eje.set_ylim(bottom=0)
    eje.set_ylabel(f"Gasto ({simbolo})", fontsize=9)
    eje.grid(axis="y", color="#dde3e8", linewidth=0.8)
    for lado in ("top", "right"):
        eje.spines[lado].set_visible(False)
    return _a_base64(figura)


# ---------------------------------------------------------------------
# Exportacion (RF09)
# ---------------------------------------------------------------------
def _neutralizar(texto):
    """Evita la inyeccion de formulas en Excel: un texto que empieza con
    los signos igual, mas, menos o arroba se interpretaria como formula al
    abrir el CSV, asi que se le antepone una comilla simple (RNF03)."""
    texto = str(texto)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def exportar_csv(df):
    """Genera el CSV de los gastos del periodo, ordenados por fecha."""
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["Fecha", "Categoria", "Descripcion", "Monto", "Metodo de pago"])
    for fila in df.sort_values("fecha").itertuples(index=False):
        escritor.writerow([
            fila.fecha.strftime("%Y-%m-%d"),
            _neutralizar(fila.categoria),
            _neutralizar(fila.descripcion),
            f"{fila.monto:.2f}",
            _neutralizar(fila.metodo_pago),
        ])
    return salida.getvalue()

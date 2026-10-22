"""
Modulo de presupuesto del Rastreador de Gastos.
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Pertenece a la capa de logica de negocio (seccion 5.2.1 de la Tarea #2).
Compara lo presupuestado con lo realmente gastado y decide cuando hay
que avisarle al usuario. No depende de Flask ni de la base de datos:
recibe diccionarios sencillos, de modo que se puede probar aislado.

Requisitos que soporta:
  RF05  definicion de un presupuesto mensual total y por categoria.
  RF10  aviso cuando el gasto de una categoria supera el porcentaje
        definido del presupuesto.
  RNF05 mantenibilidad: funciones cortas, sin estado y con una sola
        responsabilidad cada una.
"""

from reportes import MESES

# Porcentaje a partir del cual una linea del presupuesto se considera en
# riesgo. Por debajo el estado es normal; al llegar a 100 quedo excedida.
# Es el "porcentaje definido" del que habla RF10.
UMBRAL_AVISO = 80

# Estados posibles de una linea del presupuesto
NORMAL = "normal"
AVISO = "aviso"
EXCEDIDO = "excedido"
SIN_PRESUPUESTO = "sin_presupuesto"


# ---------------------------------------------------------------------
# Calculos basicos
# ---------------------------------------------------------------------
def porcentaje_consumido(gastado, asignado):
    """Porcentaje del presupuesto que ya se consumio. Si no hay monto
    asignado devuelve 0, porque no existe referencia contra la cual
    comparar."""
    if not asignado:
        return 0.0
    return round(gastado / asignado * 100, 1)


def clasificar(pct, asignado):
    """Traduce el porcentaje consumido a un estado (RF10).
    Se separa del calculo para que el umbral viva en un solo lugar."""
    if not asignado:
        return SIN_PRESUPUESTO
    if pct >= 100:
        return EXCEDIDO
    if pct >= UMBRAL_AVISO:
        return AVISO
    return NORMAL


def _linea(nombre, asignado, gastado):
    """Arma una fila de la comparacion: lo asignado, lo gastado, lo que
    resta, el porcentaje consumido y el estado resultante."""
    pct = porcentaje_consumido(gastado, asignado)
    return {
        "categoria": nombre,
        "asignado": round(asignado, 2),
        "gastado": round(gastado, 2),
        "restante": round(asignado - gastado, 2),
        "porcentaje": pct,
        # La barra no puede pasar del 100 por ciento de ancho aunque el
        # gasto si lo haga; el exceso se comunica con el color y el texto.
        "ancho": min(pct, 100),
        "estado": clasificar(pct, asignado),
    }


def gasto_por_categoria(gastos):
    """Suma los gastos recibidos agrupados por nombre de categoria.
    Recibe objetos Gasto del modelo y devuelve un diccionario simple."""
    totales = {}
    for g in gastos:
        nombre = g.categoria.nombre
        totales[nombre] = totales.get(nombre, 0.0) + float(g.monto)
    return totales


# ---------------------------------------------------------------------
# Comparacion presupuesto contra gasto real (RF05)
# ---------------------------------------------------------------------
def comparar(monto_total, asignaciones, gastado_por_categoria):
    """Punto de entrada del modulo.

    monto_total           presupuesto mensual total definido por el usuario
    asignaciones          {categoria: monto presupuestado}
    gastado_por_categoria {categoria: monto realmente gastado en el mes}

    Devuelve el total del mes, una fila por categoria y el monto que
    quedo sin repartir. Se incluyen tanto las categorias con presupuesto
    como aquellas en las que hubo gasto sin haberlo presupuestado, porque
    esas ultimas son justamente las que el usuario no tenia previstas.
    """
    monto_total = float(monto_total or 0)
    nombres = set(asignaciones) | set(gastado_por_categoria)
    lineas = [
        _linea(nombre,
               float(asignaciones.get(nombre, 0)),
               float(gastado_por_categoria.get(nombre, 0)))
        for nombre in nombres
    ]
    # Orden: primero las categorias con presupuesto, de mayor a menor
    # consumo, y al final las que no tienen monto asignado.
    lineas.sort(key=lambda l: (l["asignado"] == 0, -l["porcentaje"], l["categoria"]))

    asignado_categorias = round(sum(float(m) for m in asignaciones.values()), 2)
    total_gastado = sum(float(m) for m in gastado_por_categoria.values())
    return {
        "total": _linea("Total del mes", monto_total, total_gastado),
        "categorias": lineas,
        "asignado_categorias": asignado_categorias,
        "sin_asignar": round(monto_total - asignado_categorias, 2),
        "sobreasignado": asignado_categorias > monto_total,
        "definido": monto_total > 0 or asignado_categorias > 0,
    }


# ---------------------------------------------------------------------
# Avisos al usuario (RF10)
# ---------------------------------------------------------------------
def alertas(comparacion):
    """Lista de avisos ordenada por gravedad: primero el total del mes y
    despues cada categoria excedida o cerca del umbral. Devuelve una
    lista vacia cuando no hay presupuesto definido o todo va en orden,
    de modo que la plantilla no necesita casos especiales."""
    if not comparacion["definido"]:
        return []

    mensajes = []
    total = comparacion["total"]
    if total["estado"] == EXCEDIDO:
        mensajes.append({
            "nivel": EXCEDIDO,
            "texto": (f"Superaste el presupuesto del mes por "
                      f"${abs(total['restante']):.2f}."),
        })
    elif total["estado"] == AVISO:
        mensajes.append({
            "nivel": AVISO,
            "texto": (f"Ya consumiste el {total['porcentaje']}% del "
                      f"presupuesto del mes."),
        })

    for linea in comparacion["categorias"]:
        if linea["estado"] == EXCEDIDO:
            mensajes.append({
                "nivel": EXCEDIDO,
                "texto": (f"{linea['categoria']}: gastaste "
                          f"${linea['gastado']:.2f} de los "
                          f"${linea['asignado']:.2f} presupuestados."),
            })
        elif linea["estado"] == AVISO:
            mensajes.append({
                "nivel": AVISO,
                "texto": (f"{linea['categoria']}: llevas el "
                          f"{linea['porcentaje']}% de lo presupuestado."),
            })
    return mensajes


# ---------------------------------------------------------------------
# Utilidades de fechas
# ---------------------------------------------------------------------
def etiqueta_mes(mes, anio):
    """Nombre legible del mes para el encabezado de la pantalla."""
    return f"{MESES[mes - 1]} {anio}"


def mes_desplazado(mes, anio, pasos):
    """Mes anterior o siguiente, para los botones de navegacion."""
    indice = anio * 12 + (mes - 1) + pasos
    return indice % 12 + 1, indice // 12

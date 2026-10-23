"""
Modulo de recomendaciones de ahorro del Rastreador de Gastos.
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Pertenece a la capa de logica de negocio (seccion 5.2.1 de la Tarea #2) y
es el elemento diferenciador de la propuesta. Funciona en los dos niveles
descritos en la seccion 5.3.5:

  Nivel analitico (reglas)  calcula estadisticas de los gastos con pandas
                            y genera recomendaciones por reglas de negocio.
                            No necesita internet ni clave: siempre responde.

  Nivel generativo (IA)     envia el resumen agregado a un modelo de
                            lenguaje a traves de su API y devuelve
                            recomendaciones redactadas.

Si el servicio no esta disponible, no hay clave configurada o la respuesta
no se entiende, se usa el nivel de reglas. El sistema nunca se queda sin
recomendaciones, que es lo que justifica el diseno de respaldo.

Requisitos que soporta:
  RF08  recomendaciones de ahorro personalizadas asistidas por IA.
  RNF06 privacidad: al servicio externo solo viaja un resumen agregado.
        Nunca se envian el nombre del usuario, su correo, ni las
        descripciones de los gastos, que es donde suele haber datos
        personales. Solo categorias, montos y porcentajes.
  RNF05 mantenibilidad: el proveedor, el modelo y la clave se configuran
        con variables de entorno, sin tocar el codigo.
"""

import json
import os

import pandas as pd

import localizacion

# ---------------------------------------------------------------------
# Umbrales de las reglas de negocio
# ---------------------------------------------------------------------
UMBRAL_CRECIMIENTO = 20     # % de aumento respecto al mes anterior
UMBRAL_CONCENTRACION = 35   # % del gasto total en una sola categoria
# La concentracion solo se evalua cuando hay varias categorias entre las
# cuales repartir: con una o dos, una categoria "concentra" el gasto por
# pura aritmetica y el aviso no aportaria nada al usuario.
MINIMO_CATEGORIAS_CONCENTRACION = 3
MINIMO_MESES_RECURRENTE = 2  # meses distintos en que debe repetirse el gasto

# No todo gasto recurrente se puede cancelar. El alquiler y la luz se
# repiten todos los meses igual que una suscripcion, pero recomendar
# "cancelarlos" seria absurdo. Por eso se distinguen dos tipos:
#   cancelable  servicios opcionales que el usuario puede dar de baja
#   fijo        gastos esenciales, donde la via es renegociar o buscar
#               una alternativa mas barata, no eliminarlos
# Ante una categoria personalizada que el sistema no conoce se asume
# fijo, que es la recomendacion prudente: nunca se sugiere cancelar algo
# cuya naturaleza se desconoce.
CATEGORIAS_CANCELABLES = {"mensualidades", "entretenimiento"}
TIPO_CANCELABLE = "cancelable"
TIPO_FIJO = "fijo"


def clasificar_recurrente(categoria):
    """Decide si un gasto recurrente admite cancelacion o es esencial."""
    if categoria.strip().lower() in CATEGORIAS_CANCELABLES:
        return TIPO_CANCELABLE
    return TIPO_FIJO
MAXIMO_RECOMENDACIONES = 5

ORIGEN_REGLAS = "reglas"
ORIGEN_IA = "ia"

# Configuracion del servicio de IA. Los valores por defecto apuntan a
# Groq, que ofrece un nivel gratuito, pero sirve cualquier proveedor
# compatible con la interfaz de OpenAI cambiando IA_URL y IA_MODELO.
URL_POR_DEFECTO = "https://api.groq.com/openai/v1"
MODELO_POR_DEFECTO = "openai/gpt-oss-20b"
TIEMPO_LIMITE = 25  # segundos

# Las instrucciones son deliberadamente estrictas. En las primeras pruebas
# el modelo proponia "transferir el presupuesto no utilizado a una cuenta
# de ahorros" y lo contaba como ahorro, cuando en realidad es dinero que
# nunca se gasto: eso infla la cifra y no corresponde a ninguna decision
# del usuario. Por eso se acota que solo valen recortes de gasto real.
INSTRUCCIONES = (
    "Eres un asesor de finanzas personales. Recibiras un resumen "
    "estadistico de los gastos mensuales de una persona. "
    "Genera entre 3 y 5 recomendaciones de ahorro en espanol siguiendo "
    "estas reglas sin excepcion:\n"
    "1. Cada recomendacion debe proponer reducir, eliminar o sustituir un "
    "gasto que REALMENTE ocurrio segun el resumen.\n"
    "2. El ahorro_estimado es el recorte mensual de ese gasto, expresado "
    "como numero en la moneda indicada en el campo moneda del resumen, "
    "real, y nunca puede superar lo gastado en esa categoria.\n"
    "3. Esta prohibido presentar como ahorro el presupuesto no utilizado, "
    "el dinero que sobra o el que no se gasto: eso no es un ahorro nuevo.\n"
    "4. Esta prohibido recomendar invertir, abrir cuentas, pedir prestamos "
    "o cualquier producto financiero.\n"
    "5. No inventes gastos, categorias ni cifras que no aparezcan en el "
    "resumen. Si los datos son escasos, devuelve menos recomendaciones "
    "antes que inventar.\n"
    "6. Prioriza las categorias que se pasaron del presupuesto, las que "
    "crecieron respecto al mes anterior y los gastos recurrentes.\n"
    "7. En la lista de recurrentes, los marcados como cancelable admiten "
    "darse de baja; los marcados como fijo son esenciales (vivienda, "
    "salud, alimentacion) y para esos solo puedes sugerir renegociar o "
    "buscar alternativas mas baratas, nunca cancelarlos.\n"
    "Cada recomendacion debe ser concreta y accionable, no un consejo "
    "generico. Responde solo con un objeto JSON con esta forma: "
    '{"recomendaciones": [{"texto": "...", "ahorro_estimado": 00.00}]}'
)


# =====================================================================
# Nivel analitico: construccion del resumen (RNF06)
# =====================================================================
def detectar_recurrentes(gastos):
    """Busca suscripciones y mensualidades: un mismo gasto que reaparece
    mes tras mes.

    Dos criterios importan aqui:

    1. Se exigen MESES DISTINTOS, no repeticiones. Dos gastos del mismo
       monto dentro del mismo mes son dos compras, no una suscripcion.
    2. Se agrupa tambien por descripcion, porque dos servicios distintos
       pueden costar lo mismo (por ejemplo el telefono y un programa de
       $20 cada uno): sin ese criterio se contarian como un solo gasto
       recurrente.

    La descripcion se usa UNICAMENTE para agrupar dentro del sistema.
    No forma parte del resultado ni viaja al servicio externo, que solo
    recibe categoria, monto y cantidad de meses (RNF06).
    """
    filas = [{"categoria": g.categoria.nombre,
              "monto": round(float(g.monto), 2),
              "concepto": (getattr(g, "descripcion", "") or "").strip().lower(),
              "mes": f"{g.fecha.year}-{g.fecha.month:02d}"} for g in gastos]
    if not filas:
        return []
    df = pd.DataFrame(filas)
    conteo = (df.groupby(["categoria", "monto", "concepto"])["mes"]
                .nunique().reset_index(name="meses"))
    repetidos = conteo[conteo["meses"] >= MINIMO_MESES_RECURRENTE]
    repetidos = repetidos.sort_values("monto", ascending=False)
    return [
        {"categoria": fila.categoria,
         "monto": float(fila.monto),
         "veces": int(fila.meses),
         "tipo": clasificar_recurrente(fila.categoria)}
        for fila in repetidos.itertuples(index=False)
    ]


def construir_resumen(etiqueta, gastado_mes, gastado_anterior,
                      comparacion_presupuesto, gastos_para_recurrencia,
                      moneda=localizacion.MONEDA_POR_DEFECTO):
    """Arma el resumen agregado del mes.

    etiqueta                  texto del periodo, por ejemplo "Octubre 2026"
    gastado_mes               {categoria: total gastado este mes}
    gastado_anterior          {categoria: total gastado el mes pasado}
    comparacion_presupuesto   resultado de presupuesto.comparar()
    gastos_para_recurrencia   gastos de los dos meses, para detectar
                              montos repetidos

    El resultado es un diccionario de cifras: no contiene nombres de
    personas, correos ni descripciones (RNF06).
    """
    total = round(sum(gastado_mes.values()), 2)
    total_anterior = round(sum(gastado_anterior.values()), 2)

    categorias = []
    for nombre, monto in sorted(gastado_mes.items(), key=lambda par: -par[1]):
        anterior = round(float(gastado_anterior.get(nombre, 0)), 2)
        variacion = round((monto - anterior) / anterior * 100, 1) if anterior else None
        categorias.append({
            "categoria": nombre,
            "total": round(float(monto), 2),
            "porcentaje": round(monto / total * 100, 1) if total else 0.0,
            "anterior": anterior,
            "variacion": variacion,
        })

    lineas_presupuesto = [
        {
            "categoria": l["categoria"],
            "asignado": l["asignado"],
            "gastado": l["gastado"],
            "exceso": round(-l["restante"], 2) if l["restante"] < 0 else 0.0,
            "porcentaje": l["porcentaje"],
        }
        for l in comparacion_presupuesto["categorias"] if l["asignado"] > 0
    ]

    return {
        "periodo": etiqueta,
        "moneda": moneda,
        "total": total,
        "total_anterior": total_anterior,
        "cantidad_categorias": len(categorias),
        "categorias": categorias,
        "presupuesto": lineas_presupuesto,
        "presupuesto_total": comparacion_presupuesto["total"]["asignado"],
        "recurrentes": detectar_recurrentes(gastos_para_recurrencia),
    }


# =====================================================================
# Nivel analitico: recomendaciones por reglas (siempre disponible)
# =====================================================================
def recomendar_por_reglas(resumen):
    """Aplica las reglas de negocio sobre el resumen. Cada regla produce
    una recomendacion con su ahorro mensual estimado. Se devuelven las de
    mayor ahorro primero, hasta el maximo definido."""
    sugerencias = []

    def importe(valor):
        """Formatea un monto en la moneda del usuario. Antes el simbolo
        de dolar estaba escrito dentro de cada mensaje."""
        return localizacion.formatear(valor, resumen.get("moneda",
                                                         localizacion.MONEDA_POR_DEFECTO))

    # Regla 1: categorias que se pasaron del presupuesto.
    # El ahorro estimado es el exceso, que es lo que habria que recortar
    # para volver a lo previsto.
    for linea in resumen["presupuesto"]:
        if linea["exceso"] > 0:
            sugerencias.append({
                "texto": (f"Te pasaste del presupuesto en {linea['categoria']}: "
                          f"gastaste {importe(linea['gastado'])} de {importe(linea['asignado'])}. "
                          f"Recortar ahi te devuelve al plan del mes."),
                "ahorro_estimado": linea["exceso"],
            })

    # Regla 2: categorias que crecieron respecto al mes anterior.
    for c in resumen["categorias"]:
        if c["variacion"] is not None and c["variacion"] >= UMBRAL_CRECIMIENTO:
            sugerencias.append({
                "texto": (f"{c['categoria']} subio {c['variacion']}% respecto al mes "
                          f"anterior ({importe(c['anterior'])} a {importe(c['total'])}). "
                          f"Volver al nivel anterior seria tu ahorro mas rapido."),
                "ahorro_estimado": round(c["total"] - c["anterior"], 2),
            })

    # Regla 3: una sola categoria concentra buena parte del gasto.
    # Solo aplica si hay suficientes categorias como para que el reparto
    # sea significativo.
    hay_variedad = len(resumen["categorias"]) >= MINIMO_CATEGORIAS_CONCENTRACION
    for c in resumen["categorias"]:
        if hay_variedad and c["porcentaje"] >= UMBRAL_CONCENTRACION:
            sugerencias.append({
                "texto": (f"{c['categoria']} concentra el {c['porcentaje']}% de tu gasto "
                          f"del mes. Reducirla un 10% liberaria una parte importante "
                          f"de tu presupuesto."),
                "ahorro_estimado": round(c["total"] * 0.10, 2),
            })

    # Regla 4: gastos recurrentes, candidatos naturales a revisarse
    # porque se renuevan solos todos los meses. El consejo cambia segun
    # el gasto se pueda cancelar o sea esencial.
    for r in resumen["recurrentes"]:
        # Si el resumen no trae el tipo (por ejemplo, uno construido a
        # mano), se deduce de la categoria en lugar de asumir.
        tipo = r.get("tipo") or clasificar_recurrente(r["categoria"])
        if tipo == TIPO_CANCELABLE:
            sugerencias.append({
                "texto": (f"Detecte un gasto recurrente de {importe(r['monto'])} en "
                          f"{r['categoria']} que se repite en {r['veces']} meses. "
                          f"Si ya no lo usas, cancelarlo ahorra "
                          f"{importe(r['monto'] * 12)} al ano."),
                "ahorro_estimado": r["monto"],
            })
        else:
            sugerencias.append({
                "texto": (f"{r['categoria']} tiene un gasto fijo de "
                          f"{importe(r['monto'])} que se repite en {r['veces']} meses. "
                          f"No se puede eliminar, pero renegociarlo o buscar una "
                          f"alternativa mas barata reduciria tu gasto base; una "
                          f"rebaja del 10% serian {importe(r['monto'] * 0.10)} al mes."),
                "ahorro_estimado": round(r["monto"] * 0.10, 2),
            })

    if not sugerencias:
        # Estado sano: se devuelve una sola recomendacion en lugar de una
        # lista vacia, para que la pantalla siempre diga algo util.
        sugerencias.append({
            "texto": ("Tus gastos del mes estan dentro de lo previsto y sin "
                      "aumentos importantes. Manten el registro al dia para "
                      "seguir comparando mes a mes."),
            "ahorro_estimado": 0.0,
        })

    sugerencias.sort(key=lambda s: -s["ahorro_estimado"])
    return sugerencias[:MAXIMO_RECOMENDACIONES]


# =====================================================================
# Nivel generativo: modelo de lenguaje
# =====================================================================
def hay_clave():
    """Indica si hay clave configurada, para avisar en la pantalla sin
    tener que intentar la llamada."""
    return bool(os.environ.get("GROQ_API_KEY"))


def _cliente():
    """Crea el cliente del servicio. Se importa openai aqui dentro para
    que el resto del modulo funcione aunque la libreria no este
    instalada."""
    clave = os.environ.get("GROQ_API_KEY")
    if not clave:
        return None
    from openai import OpenAI
    return OpenAI(
        api_key=clave,
        base_url=os.environ.get("IA_URL", URL_POR_DEFECTO),
        timeout=TIEMPO_LIMITE,
    )


def _limpiar(contenido):
    """Algunos modelos envuelven el JSON en un bloque de codigo. Se quita
    antes de interpretarlo."""
    texto = contenido.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return texto.strip()


def interpretar_respuesta(contenido):
    """Convierte la respuesta del modelo en la misma estructura que
    devuelven las reglas. Se valida cada campo porque la respuesta de un
    modelo de lenguaje no es confiable por si sola."""
    datos = json.loads(_limpiar(contenido))
    crudas = datos.get("recomendaciones", []) if isinstance(datos, dict) else datos
    limpias = []
    for item in crudas:
        if not isinstance(item, dict):
            continue
        texto = str(item.get("texto", "")).strip()
        if not texto:
            continue
        try:
            ahorro = round(float(item.get("ahorro_estimado", 0)), 2)
        except (TypeError, ValueError):
            ahorro = 0.0
        limpias.append({"texto": texto, "ahorro_estimado": max(ahorro, 0.0)})
    return limpias[:MAXIMO_RECOMENDACIONES]


def recomendar_con_ia(resumen):
    """Envia el resumen agregado al modelo y devuelve sus recomendaciones.
    Devuelve una lista vacia si no hay clave o si la respuesta no sirve."""
    cliente = _cliente()
    if cliente is None:
        return []
    respuesta = cliente.chat.completions.create(
        model=os.environ.get("IA_MODELO", MODELO_POR_DEFECTO),
        temperature=0.4,
        messages=[
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content": json.dumps(resumen, ensure_ascii=False)},
        ],
    )
    return interpretar_respuesta(respuesta.choices[0].message.content)


# =====================================================================
# Cascada: IA primero, reglas como respaldo
# =====================================================================
def generar(resumen):
    """Devuelve (recomendaciones, origen, detalle_del_error).

    Se intenta primero el nivel generativo. Ante cualquier problema (sin
    clave, sin internet, limite del servicio, respuesta ilegible) se cae
    al nivel de reglas y se conserva el mensaje del error para mostrarlo
    en la pantalla, de modo que el usuario sepa por que vio reglas."""
    if not hay_clave():
        return recomendar_por_reglas(resumen), ORIGEN_REGLAS, "No hay clave de IA configurada."
    try:
        sugerencias = recomendar_con_ia(resumen)
        if sugerencias:
            return sugerencias, ORIGEN_IA, None
        return recomendar_por_reglas(resumen), ORIGEN_REGLAS, "El modelo no devolvio recomendaciones utilizables."
    except Exception as error:  # noqa: BLE001
        # Se captura cualquier excepcion a proposito: el fallo de un
        # servicio externo nunca debe tumbar la pantalla del usuario.
        return recomendar_por_reglas(resumen), ORIGEN_REGLAS, f"{type(error).__name__}: {error}"

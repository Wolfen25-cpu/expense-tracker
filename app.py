"""
Rastreador de Gastos Personales
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Aplicacion web construida con Flask (capa de logica de negocio) y
SQLite mediante SQLAlchemy (capa de datos), segun la arquitectura en
tres capas descrita en la seccion 5.2.1 de la Tarea #2.
"""

import os

from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta, timezone
from models import (db, Usuario, Categoria, Gasto,
                    Presupuesto, PresupuestoCategoria, Recomendacion)
import presupuesto
import recomendaciones
import reportes

# Lee el archivo .env y deja sus valores como variables de entorno.
# Ahi vive la clave del servicio de IA, que nunca se escribe en el codigo
# ni se sube al repositorio (RNF03).
load_dotenv()

# ---------------------------------------------------------------------
# Configuracion de la aplicacion
# RNF04 (portabilidad): SQLite es un solo archivo, sin servidor,
# por lo que la aplicacion corre igual en Windows, macOS y Linux.
# La base de datos y la clave secreta se pueden cambiar con variables de
# entorno (GASTOS_DB y GASTOS_SECRET_KEY). Esto permite que las pruebas
# automaticas usen una base de datos en memoria sin tocar los datos
# reales (pruebas de software) y que la clave no quede escrita en el
# codigo cuando se despliegue (RNF03). Sin variables se usan los valores
# de desarrollo de siempre.
# ---------------------------------------------------------------------
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("GASTOS_DB", "sqlite:///gastos.db")
app.config["SECRET_KEY"] = os.environ.get("GASTOS_SECRET_KEY", "clave-temporal-de-desarrollo")
db.init_app(app)

# Gestion de sesiones de usuario (RF01)
login_manager = LoginManager(app)
login_manager.login_view = "login"


# Zona horaria en la que se muestran las fechas. Se guarda todo en UTC y
# se convierte solo al presentarlo, para que el sistema siga mostrando la
# hora correcta aunque se despliegue en un servidor de otro pais (RNF04).
ZONA_HORARIA = os.environ.get("ZONA_HORARIA", "America/Puerto_Rico")


@app.template_filter("fecha_local")
def fecha_local(momento, formato="%d/%m/%Y %I:%M %p"):
    """Convierte a la zona horaria configurada una marca de tiempo
    guardada en UTC. Si la zona no esta disponible en el sistema se
    muestra la hora tal cual, sin romper la pagina."""
    if momento is None:
        return ""
    try:
        from zoneinfo import ZoneInfo
        local = momento.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(ZONA_HORARIA))
    except Exception:  # noqa: BLE001
        local = momento
    return local.strftime(formato)


@login_manager.user_loader
def cargar_usuario(user_id):
    """Recupera el usuario conectado a partir del id guardado en la sesion."""
    return db.session.get(Usuario, int(user_id))


# Categorias base del sistema (RF04)
CATEGORIAS_BASE = ["Alimentación", "Transporte", "Vivienda", "Salud",
                   "Entretenimiento", "Educación", "Mensualidades", "Otros"]


# =====================================================================
# RF01: Gestion de usuarios (registro, autenticacion, cierre de sesion)
# =====================================================================

@app.route("/registro", methods=["GET", "POST"])
def registro():
    """Crea una cuenta nueva.
    RNF03 (seguridad): la contrasena se almacena con hash irreversible
    mediante generate_password_hash; el correo es unico en la tabla."""
    if request.method == "POST":
        correo = request.form["correo"]
        if Usuario.query.filter_by(correo=correo).first():
            return "Ese correo ya está registrado. <a href='/registro'>Volver</a>"
        usuario = Usuario(
            nombre=request.form["nombre"],
            correo=correo,
            contrasena_hash=generate_password_hash(request.form["contrasena"])
        )
        db.session.add(usuario)
        db.session.commit()
        login_user(usuario)
        return redirect(url_for("inicio"))
    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Autentica al usuario comparando el hash almacenado.
    RNF03: nunca se compara la contrasena en texto plano."""
    if request.method == "POST":
        usuario = Usuario.query.filter_by(correo=request.form["correo"]).first()
        if usuario and check_password_hash(usuario.contrasena_hash, request.form["contrasena"]):
            login_user(usuario)
            return redirect(url_for("inicio"))
        return "Correo o contraseña incorrectos. <a href='/login'>Volver</a>"
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    """Cierra la sesion activa."""
    logout_user()
    return redirect(url_for("login"))


# =====================================================================
# RF02 y RF04: Registro y listado de gastos con categorias
# =====================================================================

@app.route("/")
@login_required
def inicio():
    """Pantalla principal. Redirige a la vista de gastos."""
    return redirect(url_for("gastos"))


@app.route("/gastos", methods=["GET", "POST"])
@login_required
def gastos():
    """RF02: registra un gasto nuevo con fecha, monto, categoria,
    descripcion y metodo de pago, y lista los gastos del usuario.

    RNF03: el filtro por usuario_id garantiza que cada usuario solo
    accede a sus propios datos."""
    if request.method == "POST":
        gasto = Gasto(
            fecha=datetime.strptime(request.form["fecha"], "%Y-%m-%d").date(),
            monto=float(request.form["monto"]),
            descripcion=request.form.get("descripcion"),
            metodo_pago=request.form.get("metodo_pago"),
            categoria_id=int(request.form["categoria_id"]),
            usuario_id=current_user.id
        )
        db.session.add(gasto)
        db.session.commit()
        return redirect(url_for("gastos"))

    mis_gastos = (Gasto.query
                  .filter_by(usuario_id=current_user.id)
                  .order_by(Gasto.fecha.desc(), Gasto.id.desc())
                  .all())
    categorias = Categoria.query.filter_by(es_predefinida=True).all()
    total = sum(g.monto for g in mis_gastos)
    # RF10: los avisos del mes en curso se muestran en la misma pantalla
    # donde el usuario registra, que es donde puede reaccionar a tiempo.
    hoy = date.today()
    avisos = presupuesto.alertas(_comparacion_del_mes(hoy.month, hoy.year))
    return render_template("gastos.html",
                           gastos=mis_gastos,
                           categorias=categorias,
                           total=total,
                           avisos=avisos,
                           hoy=hoy.isoformat())


# =====================================================================
# RF03: Edicion y eliminacion de gastos
# =====================================================================

@app.route("/gastos/<int:gasto_id>/editar", methods=["GET", "POST"])
@login_required
def editar_gasto(gasto_id):
    """RF03: modifica un gasto existente.
    RNF03: first_or_404 sobre id y usuario_id impide editar el gasto
    de otro usuario manipulando la URL."""
    gasto = Gasto.query.filter_by(id=gasto_id, usuario_id=current_user.id).first_or_404()
    if request.method == "POST":
        gasto.fecha = datetime.strptime(request.form["fecha"], "%Y-%m-%d").date()
        gasto.monto = float(request.form["monto"])
        gasto.descripcion = request.form.get("descripcion")
        gasto.metodo_pago = request.form.get("metodo_pago")
        gasto.categoria_id = int(request.form["categoria_id"])
        db.session.commit()
        return redirect(url_for("gastos"))

    categorias = Categoria.query.filter_by(es_predefinida=True).all()
    return render_template("editar_gasto.html", gasto=gasto, categorias=categorias)


@app.route("/gastos/<int:gasto_id>/eliminar", methods=["POST"])
@login_required
def eliminar_gasto(gasto_id):
    """RF03: elimina un gasto propio. Se usa POST y no GET para que la
    accion no sea ejecutable desde un simple enlace."""
    gasto = Gasto.query.filter_by(id=gasto_id, usuario_id=current_user.id).first_or_404()
    db.session.delete(gasto)
    db.session.commit()
    return redirect(url_for("gastos"))


# =====================================================================
# RF05 y RF10: Presupuesto mensual y avisos
# Los calculos viven en presupuesto.py; aqui solo se leen y guardan
# los datos y se coordina la pantalla.
# =====================================================================

def _monto(texto):
    """Convierte el texto de un campo del formulario en un monto valido.
    Un campo vacio o con texto invalido vale cero, que es la forma de
    indicar que esa categoria no tiene presupuesto asignado."""
    try:
        valor = float(texto)
    except (TypeError, ValueError):
        return 0.0
    return valor if valor > 0 else 0.0


def _mes_anio(origen):
    """Lee el mes y el anio de la peticion (de la URL o del formulario).
    Ante cualquier valor invalido se usa el mes en curso, de modo que una
    direccion manipulada nunca produce un error (RNF01)."""
    hoy = date.today()
    try:
        mes = int(origen.get("mes", hoy.month))
        anio = int(origen.get("anio", hoy.year))
    except (TypeError, ValueError):
        return hoy.month, hoy.year
    if not 1 <= mes <= 12 or not 2000 <= anio <= 2100:
        return hoy.month, hoy.year
    return mes, anio


def _presupuesto_del_mes(mes, anio, crear=False):
    """Presupuesto del usuario conectado para ese mes, o None si todavia
    no lo definio. Con crear=True lo crea vacio en lugar de devolver None.
    RNF03: el filtro por usuario_id aisla los datos de cada usuario."""
    registro = Presupuesto.query.filter_by(
        usuario_id=current_user.id, mes=mes, anio=anio).first()
    if registro is None and crear:
        registro = Presupuesto(mes=mes, anio=anio, monto_total=0.0,
                               usuario_id=current_user.id)
        db.session.add(registro)
    return registro


def _rango_del_mes(mes, anio):
    """Primer y ultimo dia del mes, ambos inclusivos."""
    inicio = date(anio, mes, 1)
    siguiente = (inicio + timedelta(days=32)).replace(day=1)
    return inicio, siguiente - timedelta(days=1)


def _comparacion_del_mes(mes, anio):
    """RF05: compara el presupuesto definido con el gasto real del mes."""
    inicio, fin = _rango_del_mes(mes, anio)
    gastos_mes = (Gasto.query
                  .filter(Gasto.usuario_id == current_user.id,
                          Gasto.fecha >= inicio,
                          Gasto.fecha <= fin)
                  .all())
    registro = _presupuesto_del_mes(mes, anio)
    asignaciones = ({d.categoria.nombre: d.monto for d in registro.detalles}
                    if registro else {})
    return presupuesto.comparar(
        registro.monto_total if registro else 0.0,
        asignaciones,
        presupuesto.gasto_por_categoria(gastos_mes),
    )


@app.route("/presupuesto", methods=["GET", "POST"])
@login_required
def presupuesto_mensual():
    """RF05: define el presupuesto mensual total y por categoria, y
    muestra cuanto se lleva consumido de cada uno.
    RF10: lista los avisos de las categorias que pasaron el umbral."""
    if request.method == "POST":
        mes, anio = _mes_anio(request.form)
        registro = _presupuesto_del_mes(mes, anio, crear=True)
        registro.monto_total = _monto(request.form.get("monto_total"))

        # Se recorren todas las categorias: las que traen monto se crean
        # o se actualizan, y las que quedaron en blanco se eliminan del
        # detalle para no dejar presupuestos en cero.
        existentes = {d.categoria_id: d for d in registro.detalles}
        for categoria in Categoria.query.filter_by(es_predefinida=True).all():
            monto = _monto(request.form.get(f"categoria_{categoria.id}"))
            detalle = existentes.get(categoria.id)
            if monto > 0 and detalle is not None:
                detalle.monto = monto
            elif monto > 0:
                db.session.add(PresupuestoCategoria(
                    presupuesto=registro, categoria_id=categoria.id, monto=monto))
            elif detalle is not None:
                db.session.delete(detalle)
        db.session.commit()
        return redirect(url_for("presupuesto_mensual", mes=mes, anio=anio))

    mes, anio = _mes_anio(request.args)
    registro = _presupuesto_del_mes(mes, anio)
    comparacion = _comparacion_del_mes(mes, anio)
    mes_anterior, anio_anterior = presupuesto.mes_desplazado(mes, anio, -1)
    mes_siguiente, anio_siguiente = presupuesto.mes_desplazado(mes, anio, 1)
    return render_template(
        "presupuesto.html",
        c=comparacion,
        avisos=presupuesto.alertas(comparacion),
        categorias=Categoria.query.filter_by(es_predefinida=True).all(),
        # Montos ya guardados, por id de categoria, para precargar el formulario
        asignado={d.categoria_id: d.monto for d in registro.detalles} if registro else {},
        monto_total=registro.monto_total if registro else 0.0,
        mes=mes,
        anio=anio,
        etiqueta=presupuesto.etiqueta_mes(mes, anio),
        umbral=presupuesto.UMBRAL_AVISO,
        anterior={"mes": mes_anterior, "anio": anio_anterior},
        siguiente={"mes": mes_siguiente, "anio": anio_siguiente},
    )


# =====================================================================
# RF06, RF07 y RF09: Reportes, graficas y exportacion
# Los calculos viven en reportes.py; aqui solo se coordinan.
# =====================================================================

def _parametros_reporte():
    """Lee el periodo y la fecha de referencia de la URL. Si faltan o
    son invalidos se usan valores seguros (mensual y hoy), de modo que
    una URL manipulada nunca produce un error (RNF01)."""
    periodo = request.args.get("periodo", "mensual")
    if periodo not in reportes.PERIODOS:
        periodo = "mensual"
    try:
        referencia = datetime.strptime(request.args.get("fecha", ""), "%Y-%m-%d").date()
    except ValueError:
        referencia = date.today()
    return periodo, referencia


def _reporte_del_usuario(periodo, referencia):
    """Lee de la base de datos solo los gastos del usuario conectado
    dentro del rango necesario y calcula el reporte.
    RNF03: el filtro por usuario_id aisla los datos de cada usuario."""
    desde, hasta = reportes.rango_consulta(periodo, referencia)
    gastos_usuario = (Gasto.query
                      .filter(Gasto.usuario_id == current_user.id,
                              Gasto.fecha >= desde,
                              Gasto.fecha <= hasta)
                      .all())
    return reportes.calcular_reporte(gastos_usuario, periodo, referencia)


@app.route("/reportes")
@login_required
def reporte():
    """RF06 y RF07: muestra el resumen del periodo elegido, los totales
    por categoria y las dos graficas."""
    periodo, referencia = _parametros_reporte()
    datos = _reporte_del_usuario(periodo, referencia)
    return render_template(
        "reportes.html",
        r=datos,
        periodos=reportes.PERIODOS,
        referencia=referencia.isoformat(),
        anterior=reportes.desplazar(periodo, referencia, -1).isoformat(),
        siguiente=reportes.desplazar(periodo, referencia, 1).isoformat(),
        grafica_distribucion=reportes.grafica_distribucion(datos["categorias"]),
        grafica_evolucion=reportes.grafica_evolucion(datos["evolucion"]),
    )


@app.route("/reportes/exportar.csv")
@login_required
def exportar_reporte():
    """RF09: descarga los gastos del periodo en CSV. Se codifica con
    utf-8-sig para que Excel muestre bien las tildes."""
    periodo, referencia = _parametros_reporte()
    datos = _reporte_del_usuario(periodo, referencia)
    contenido = reportes.exportar_csv(datos["df"]).encode("utf-8-sig")
    nombre = f"gastos_{periodo}_{datos['inicio'].isoformat()}.csv"
    return Response(contenido, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nombre}"})


# =====================================================================
# RF08: Recomendaciones de ahorro asistidas por inteligencia artificial
# La logica vive en recomendaciones.py; aqui se reunen los datos, se
# guarda el resultado y se coordina la pantalla.
# =====================================================================

def _resumen_para_recomendar(mes, anio):
    """Reune el resumen agregado del mes que se enviara al analizador.
    Lee los gastos del mes y del mes anterior (para medir variaciones y
    detectar montos repetidos) y la comparacion contra el presupuesto.
    RNF03: todas las consultas filtran por usuario_id."""
    inicio, fin = _rango_del_mes(mes, anio)
    mes_previo, anio_previo = presupuesto.mes_desplazado(mes, anio, -1)
    inicio_previo, fin_previo = _rango_del_mes(mes_previo, anio_previo)

    def _gastos_entre(desde, hasta):
        return (Gasto.query
                .filter(Gasto.usuario_id == current_user.id,
                        Gasto.fecha >= desde,
                        Gasto.fecha <= hasta)
                .all())

    gastos_mes = _gastos_entre(inicio, fin)
    gastos_previos = _gastos_entre(inicio_previo, fin_previo)
    return recomendaciones.construir_resumen(
        presupuesto.etiqueta_mes(mes, anio),
        presupuesto.gasto_por_categoria(gastos_mes),
        presupuesto.gasto_por_categoria(gastos_previos),
        _comparacion_del_mes(mes, anio),
        gastos_mes + gastos_previos,
    )


@app.route("/recomendaciones")
@login_required
def ver_recomendaciones():
    """RF08: muestra el historial de recomendaciones del usuario y el
    resumen del mes sobre el que se generarian las proximas."""
    mes, anio = _mes_anio(request.args)
    historial = (Recomendacion.query
                 .filter_by(usuario_id=current_user.id)
                 .order_by(Recomendacion.fecha.desc(), Recomendacion.id.desc())
                 .limit(20)
                 .all())
    return render_template(
        "recomendaciones.html",
        resumen=_resumen_para_recomendar(mes, anio),
        historial=historial,
        mes=mes,
        anio=anio,
        etiqueta=presupuesto.etiqueta_mes(mes, anio),
        hay_clave=recomendaciones.hay_clave(),
        error=request.args.get("error"),
        origen=request.args.get("origen"),
    )


@app.route("/recomendaciones/generar", methods=["POST"])
@login_required
def generar_recomendaciones():
    """RF08: genera un conjunto nuevo de recomendaciones y lo guarda.
    Se hace con un boton y no al cargar la pagina para no llamar al
    servicio externo en cada visita."""
    mes, anio = _mes_anio(request.form)
    sugerencias, origen, error = recomendaciones.generar(
        _resumen_para_recomendar(mes, anio))
    for sugerencia in sugerencias:
        db.session.add(Recomendacion(
            texto=sugerencia["texto"],
            ahorro_estimado=sugerencia["ahorro_estimado"],
            origen=origen,
            usuario_id=current_user.id,
        ))
    db.session.commit()
    return redirect(url_for("ver_recomendaciones", mes=mes, anio=anio,
                            origen=origen, error=error))


@app.route("/recomendaciones/<int:recomendacion_id>/aplicar", methods=["POST"])
@login_required
def aplicar_recomendacion(recomendacion_id):
    """Marca una recomendacion como aplicada o la desmarca. Este historial
    es el que permitira medir en la validacion si el usuario cambia su
    conducta (seccion 5.3.5 de la Tarea #2)."""
    recomendacion = Recomendacion.query.filter_by(
        id=recomendacion_id, usuario_id=current_user.id).first_or_404()
    recomendacion.aplicada = not recomendacion.aplicada
    db.session.commit()
    return redirect(url_for("ver_recomendaciones"))


# ---------------------------------------------------------------------
# Inicializacion de la base de datos
# Crea las tablas si no existen y carga las categorias predefinidas
# que falten, sin duplicar las ya creadas (RF04).
# ---------------------------------------------------------------------
with app.app_context():
    db.create_all()
    for nombre in CATEGORIAS_BASE:
        if not Categoria.query.filter_by(nombre=nombre, es_predefinida=True).first():
            db.session.add(Categoria(nombre=nombre, es_predefinida=True))
    db.session.commit()


if __name__ == "__main__":
    app.run(debug=True)
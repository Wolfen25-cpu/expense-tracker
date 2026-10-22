"""
Rastreador de Gastos Personales
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Aplicacion web construida con Flask (capa de logica de negocio) y
SQLite mediante SQLAlchemy (capa de datos), segun la arquitectura en
tres capas descrita en la seccion 5.2.1 de la Tarea #2.
"""

import os

from flask import Flask, Response, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime
from models import db, Usuario, Categoria, Gasto
import reportes

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
    return render_template("gastos.html",
                           gastos=mis_gastos,
                           categorias=categorias,
                           total=total,
                           hoy=date.today().isoformat())


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
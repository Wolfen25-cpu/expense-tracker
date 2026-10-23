"""
Rastreador de Gastos Personales
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Aplicacion web construida con Flask (capa de logica de negocio) y
SQLite mediante SQLAlchemy (capa de datos), segun la arquitectura en
tres capas descrita en la seccion 5.2.1 de la Tarea #2.
"""

import os
import re
import sqlite3

from dotenv import load_dotenv
from flask import (Flask, Response, flash, render_template, request,
                   redirect, url_for)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta, timezone
from models import (db, Usuario, Categoria, Gasto,
                    Presupuesto, PresupuestoCategoria, Recomendacion)
import localizacion
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
CLAVE_DE_DESARROLLO = "clave-temporal-de-desarrollo"
app.config["SECRET_KEY"] = os.environ.get("GASTOS_SECRET_KEY", CLAVE_DE_DESARROLLO)
db.init_app(app)

# ---------------------------------------------------------------------
# Seguridad de la sesion (RNF03)
#   HTTPONLY   la cookie de sesion no puede leerse desde JavaScript, lo
#              que limita el robo de sesion si hubiera un XSS.
#   SAMESITE   el navegador no envia la cookie en peticiones que vengan
#              de otro sitio, primera barrera contra CSRF.
#   SECURE     la cookie solo viaja por HTTPS. Se activa al desplegar
#              con la variable GASTOS_COOKIE_SEGURA=1; en desarrollo se
#              deja apagada porque se trabaja sobre http://127.0.0.1.
# ---------------------------------------------------------------------
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("GASTOS_COOKIE_SEGURA", "0") == "1",
)

# Proteccion contra CSRF (falsificacion de peticiones entre sitios).
# Sin esto, una pagina maliciosa abierta en otra pestana podria enviar
# un formulario a esta aplicacion aprovechando la sesion ya iniciada del
# usuario, por ejemplo para borrar sus gastos. CSRFProtect exige que todo
# formulario POST incluya un token que solo esta aplicacion conoce.
csrf = CSRFProtect(app)

# SQLite no verifica las claves foraneas a menos que se le pida en cada
# conexion. Sin esta linea se podrian guardar gastos apuntando a
# categorias que no existen y la base quedaria inconsistente.
@event.listens_for(Engine, "connect")
def _activar_claves_foraneas(conexion, _registro):
    if isinstance(conexion, sqlite3.Connection):
        cursor = conexion.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


if (app.config["SECRET_KEY"] == CLAVE_DE_DESARROLLO
        and os.environ.get("GASTOS_ENTORNO") == "produccion"):
    raise RuntimeError(
        "Define GASTOS_SECRET_KEY antes de desplegar: con la clave de "
        "desarrollo cualquiera podria falsificar sesiones de usuario.")

# Gestion de sesiones de usuario (RF01)
login_manager = LoginManager(app)
login_manager.login_view = "login"


# Zona horaria en la que se muestran las fechas. Se guarda todo en UTC y
# se convierte solo al presentarlo, para que el sistema siga mostrando la
# hora correcta aunque se despliegue en un servidor de otro pais (RNF04).
ZONA_HORARIA = os.environ.get("ZONA_HORARIA", "America/Puerto_Rico")


@app.template_filter("fecha_local")
def fecha_local(momento, formato="%d/%m/%Y %I:%M %p"):
    """Convierte a la hora del usuario una marca de tiempo guardada en
    UTC. Cada usuario tiene su propia zona horaria en el perfil; si no
    la ha definido se usa la del servidor. Si la zona no esta disponible
    en el sistema se muestra la hora tal cual, sin romper la pagina."""
    if momento is None:
        return ""
    zona = getattr(current_user, "zona_horaria", None) or ZONA_HORARIA
    try:
        from zoneinfo import ZoneInfo
        local = momento.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zona))
    except Exception:  # noqa: BLE001
        local = momento
    return local.strftime(formato)


@app.template_filter("moneda")
def formato_moneda(valor):
    """Muestra un monto en la moneda que el usuario eligio en su perfil.

    Antes el simbolo de dolar estaba escrito a mano en cada plantilla, lo
    que ataba el sistema a un solo pais. Con este filtro el formato vive
    en un unico lugar (RNF05) y cada usuario ve sus cifras como las
    escribiria en su pais (RNF01)."""
    codigo = getattr(current_user, "moneda", None) or localizacion.MONEDA_POR_DEFECTO
    return localizacion.formatear(valor, codigo)


@app.template_filter("simbolo_moneda")
def simbolo_moneda(_valor=None):
    """Solo el simbolo, para los textos donde no va una cifra."""
    codigo = getattr(current_user, "moneda", None) or localizacion.MONEDA_POR_DEFECTO
    return localizacion.simbolo(codigo)


@login_manager.user_loader
def cargar_usuario(user_id):
    """Recupera el usuario conectado a partir del id guardado en la sesion."""
    return db.session.get(Usuario, int(user_id))


# =====================================================================
# Validacion de datos de entrada (RNF03)
# Nunca se confia en lo que llega del formulario: el navegador valida
# para comodidad del usuario, pero cualquiera puede enviar una peticion
# saltandose esa validacion. Todo se vuelve a comprobar en el servidor.
# =====================================================================

MONTO_MAXIMO = 1_000_000.00
FECHA_MINIMA = date(2000, 1, 1)
LARGO_MINIMO_CLAVE = 8
LARGO_MAXIMO_NOMBRE = 100
LARGO_MAXIMO_DESCRIPCION = 200
LARGO_MAXIMO_CATEGORIA = 60
LARGO_MAXIMO_CIUDAD = 80

METODOS_PAGO = ["Efectivo", "Tarjeta de débito", "Tarjeta de crédito",
                "Transferencia", "Otro"]

PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _texto(valor, largo_maximo):
    """Limpia un texto del formulario y lo recorta al largo que admite la
    base de datos, para que un envio manipulado no provoque un error."""
    return (valor or "").strip()[:largo_maximo]


def _validar_monto(valor):
    """Devuelve (monto, error). Un monto debe ser un numero positivo y
    razonable: el formulario dice min=0, pero eso solo lo respeta el
    navegador."""
    try:
        monto = round(float(valor), 2)
    except (TypeError, ValueError):
        return None, "El monto debe ser un número."
    if monto <= 0:
        return None, "El monto debe ser mayor que cero."
    if monto > MONTO_MAXIMO:
        return None, "El monto excede el máximo permitido."
    return monto, None


def _validar_fecha(valor):
    """Devuelve (fecha, error). Se acotan las fechas absurdas, tanto
    hacia atras como hacia adelante."""
    try:
        fecha = datetime.strptime(valor, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, "La fecha no tiene un formato válido."
    if fecha < FECHA_MINIMA:
        return None, "La fecha es demasiado antigua."
    if fecha > date.today() + timedelta(days=365):
        return None, "La fecha está demasiado lejos en el futuro."
    return fecha, None


def _moneda_del_usuario():
    """Codigo de moneda del usuario conectado. Las cuentas creadas antes
    de que existiera el perfil pueden tenerlo vacio, de ahi el respaldo."""
    return getattr(current_user, "moneda", None) or localizacion.MONEDA_POR_DEFECTO


def _categorias_disponibles():
    """Categorias que puede usar el usuario conectado: las predefinidas
    del sistema mas las que el mismo haya creado (RF04)."""
    return (Categoria.query
            .filter(db.or_(Categoria.es_predefinida.is_(True),
                           Categoria.usuario_id == current_user.id))
            .order_by(Categoria.es_predefinida.desc(), Categoria.nombre)
            .all())


def _validar_categoria(valor):
    """Devuelve (categoria, error). Comprueba que la categoria exista y
    que sea del sistema o del propio usuario: sin esta verificacion,
    alguien podria enviar el identificador de la categoria privada de
    otra persona y asociarle sus gastos (RNF03)."""
    try:
        identificador = int(valor)
    except (TypeError, ValueError):
        return None, "La categoría no es válida."
    categoria = db.session.get(Categoria, identificador)
    if categoria is None:
        return None, "La categoría no existe."
    if not categoria.es_predefinida and categoria.usuario_id != current_user.id:
        return None, "La categoría no es válida."
    return categoria, None


def _validar_metodo_pago(valor):
    """Solo se aceptan los metodos de la lista. Cualquier otro texto se
    guarda como Otro en lugar de almacenarse tal cual."""
    return valor if valor in METODOS_PAGO else "Otro"


def _datos_del_gasto(formulario):
    """Valida de una vez todos los campos de un gasto.
    Devuelve (datos, error) y se usa tanto al crear como al editar."""
    fecha, error = _validar_fecha(formulario.get("fecha"))
    if error:
        return None, error
    monto, error = _validar_monto(formulario.get("monto"))
    if error:
        return None, error
    categoria, error = _validar_categoria(formulario.get("categoria_id"))
    if error:
        return None, error
    return {
        "fecha": fecha,
        "monto": monto,
        "descripcion": _texto(formulario.get("descripcion"), LARGO_MAXIMO_DESCRIPCION),
        "metodo_pago": _validar_metodo_pago(formulario.get("metodo_pago")),
        "categoria_id": categoria.id,
    }, None


# Categorias base del sistema (RF04)
CATEGORIAS_BASE = ["Alimentación", "Transporte", "Vivienda", "Salud",
                   "Entretenimiento", "Educación", "Mensualidades", "Otros"]


# =====================================================================
# RF01: Gestion de usuarios (registro, autenticacion, cierre de sesion)
# =====================================================================

def _normalizar_correo(valor):
    """Los correos se guardan en minusculas y sin espacios. De lo
    contrario "Ana@x.com" y "ana@x.com" crearian dos cuentas distintas
    para la misma persona y el inicio de sesion fallaria segun como se
    escribiera."""
    return (valor or "").strip().lower()


@app.route("/registro", methods=["GET", "POST"])
def registro():
    """Crea una cuenta nueva.
    RNF03: la contrasena se almacena con hash irreversible mediante
    generate_password_hash, el correo es unico, y todas las reglas se
    verifican en el servidor y no solo en el formulario."""
    if request.method == "POST":
        nombre = _texto(request.form.get("nombre"), LARGO_MAXIMO_NOMBRE)
        correo = _normalizar_correo(request.form.get("correo"))
        clave = request.form.get("contrasena") or ""

        if not nombre:
            return render_template("registro.html", error="Escribe tu nombre.")
        if not PATRON_CORREO.match(correo):
            return render_template("registro.html", error="El correo no es válido.")
        if len(clave) < LARGO_MINIMO_CLAVE:
            return render_template(
                "registro.html",
                error=f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.")
        if Usuario.query.filter_by(correo=correo).first():
            return render_template("registro.html", error="Ese correo ya está registrado.")

        usuario = Usuario(nombre=nombre, correo=correo,
                          contrasena_hash=generate_password_hash(clave))
        db.session.add(usuario)
        db.session.commit()
        login_user(usuario)
        return redirect(url_for("inicio"))
    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Autentica al usuario comparando el hash almacenado.
    RNF03: nunca se compara la contrasena en texto plano, y el mensaje de
    error es el mismo tanto si falla el correo como la contrasena, para
    no revelar que correos estan registrados en el sistema."""
    if request.method == "POST":
        correo = _normalizar_correo(request.form.get("correo"))
        clave = request.form.get("contrasena") or ""
        usuario = Usuario.query.filter_by(correo=correo).first()
        if usuario and check_password_hash(usuario.contrasena_hash, clave):
            login_user(usuario)
            return redirect(url_for("inicio"))
        return render_template("login.html", error="Correo o contraseña incorrectos.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    """Cierra la sesion activa. Se usa POST y no un enlace para que otra
    pagina no pueda cerrar la sesion del usuario con solo cargar una
    imagen que apunte a esta direccion (RNF03)."""
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
        datos, error = _datos_del_gasto(request.form)
        if error:
            return redirect(url_for("gastos", error=error))
        db.session.add(Gasto(usuario_id=current_user.id, **datos))
        db.session.commit()
        return redirect(url_for("gastos"))

    mis_gastos = (Gasto.query
                  .filter_by(usuario_id=current_user.id)
                  .order_by(Gasto.fecha.desc(), Gasto.id.desc())
                  .all())
    categorias = _categorias_disponibles()
    total = sum(g.monto for g in mis_gastos)
    # RF10: los avisos del mes en curso se muestran en la misma pantalla
    # donde el usuario registra, que es donde puede reaccionar a tiempo.
    hoy = date.today()
    avisos = presupuesto.alertas(_comparacion_del_mes(hoy.month, hoy.year))
    return render_template("gastos.html",
                           gastos=mis_gastos,
                           categorias=categorias,
                           metodos=METODOS_PAGO,
                           total=total,
                           avisos=avisos,
                           error=request.args.get("error"),
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
        datos, error = _datos_del_gasto(request.form)
        if not error:
            for campo, valor in datos.items():
                setattr(gasto, campo, valor)
            db.session.commit()
            return redirect(url_for("gastos"))
        return render_template("editar_gasto.html", gasto=gasto,
                               categorias=_categorias_disponibles(),
                               metodos=METODOS_PAGO, error=error)

    return render_template("editar_gasto.html", gasto=gasto,
                           categorias=_categorias_disponibles(),
                           metodos=METODOS_PAGO)


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
# Perfil del usuario
# Datos personales y preferencias de localizacion, cambio de contrasena
# y baja de la cuenta. Son funciones esperadas en cualquier aplicacion
# actual: el usuario debe poder corregir sus datos, cambiar su clave sin
# ayuda de un administrador y darse de baja llevandose sus datos.
# =====================================================================

@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    """Muestra y actualiza los datos del usuario y sus preferencias.

    RNF03: el correo se vuelve a validar y se comprueba que no este en
    uso por otra cuenta; la moneda, el pais y la zona horaria se
    verifican contra las listas conocidas antes de guardarse, para que
    un envio manipulado no inserte valores arbitrarios."""
    if request.method == "POST":
        nombre = _texto(request.form.get("nombre"), LARGO_MAXIMO_NOMBRE)
        correo = _normalizar_correo(request.form.get("correo"))

        if not nombre:
            flash("Escribe tu nombre.", "error")
            return redirect(url_for("perfil"))
        if not PATRON_CORREO.match(correo):
            flash("El correo no es válido.", "error")
            return redirect(url_for("perfil"))

        en_uso = Usuario.query.filter(Usuario.correo == correo,
                                      Usuario.id != current_user.id).first()
        if en_uso is not None:
            flash("Ese correo ya pertenece a otra cuenta.", "error")
            return redirect(url_for("perfil"))

        current_user.nombre = nombre
        current_user.correo = correo
        current_user.pais = localizacion.pais_valido(request.form.get("pais"))
        current_user.ciudad = _texto(request.form.get("ciudad"), LARGO_MAXIMO_CIUDAD)
        current_user.moneda = localizacion.moneda_valida(request.form.get("moneda"))
        current_user.zona_horaria = localizacion.zona_valida(request.form.get("zona_horaria"))
        db.session.commit()
        flash("Perfil actualizado.", "ok")
        return redirect(url_for("perfil"))

    # Resumen de actividad de la cuenta, util antes de darse de baja
    resumen_cuenta = {
        "gastos": Gasto.query.filter_by(usuario_id=current_user.id).count(),
        "categorias": Categoria.query.filter_by(usuario_id=current_user.id).count(),
        "presupuestos": Presupuesto.query.filter_by(usuario_id=current_user.id).count(),
        "recomendaciones": Recomendacion.query.filter_by(usuario_id=current_user.id).count(),
    }
    return render_template("perfil.html",
                           paises=localizacion.PAISES,
                           monedas=localizacion.MONEDAS,
                           zonas=localizacion.ZONAS_HORARIAS,
                           largo_minimo_clave=LARGO_MINIMO_CLAVE,
                           resumen=resumen_cuenta)


@app.route("/perfil/contrasena", methods=["POST"])
@login_required
def cambiar_contrasena():
    """Cambia la contrasena.

    RNF03: se exige la contrasena actual. Sin ese paso, cualquiera que
    encontrara una sesion abierta podria apoderarse de la cuenta
    cambiando la clave, y el dueno quedaria fuera."""
    actual = request.form.get("actual") or ""
    nueva = request.form.get("nueva") or ""
    confirmacion = request.form.get("confirmacion") or ""

    if not check_password_hash(current_user.contrasena_hash, actual):
        flash("La contraseña actual no es correcta.", "error")
    elif len(nueva) < LARGO_MINIMO_CLAVE:
        flash(f"La contraseña nueva debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.",
              "error")
    elif nueva != confirmacion:
        flash("La confirmación no coincide con la contraseña nueva.", "error")
    elif nueva == actual:
        flash("La contraseña nueva debe ser distinta de la actual.", "error")
    else:
        current_user.contrasena_hash = generate_password_hash(nueva)
        db.session.commit()
        flash("Contraseña actualizada.", "ok")
    return redirect(url_for("perfil"))


@app.route("/perfil/eliminar", methods=["POST"])
@login_required
def eliminar_cuenta():
    """Da de baja la cuenta y borra todos sus datos.

    Poder eliminar la propia cuenta es un derecho basico del usuario y un
    requisito de las normas de privacidad vigentes. Se pide la
    contrasena porque la accion es irreversible, y se borran primero los
    datos que dependen del usuario para respetar la integridad
    referencial de la base."""
    if not check_password_hash(current_user.contrasena_hash,
                               request.form.get("contrasena") or ""):
        flash("La contraseña no es correcta. La cuenta no se eliminó.", "error")
        return redirect(url_for("perfil"))

    usuario_id = current_user.id
    for presupuesto_usuario in Presupuesto.query.filter_by(usuario_id=usuario_id).all():
        for detalle in list(presupuesto_usuario.detalles):
            db.session.delete(detalle)
        db.session.delete(presupuesto_usuario)
    for gasto in Gasto.query.filter_by(usuario_id=usuario_id).all():
        db.session.delete(gasto)
    for recomendacion in Recomendacion.query.filter_by(usuario_id=usuario_id).all():
        db.session.delete(recomendacion)
    for categoria in Categoria.query.filter_by(usuario_id=usuario_id).all():
        db.session.delete(categoria)
    db.session.flush()

    usuario = db.session.get(Usuario, usuario_id)
    logout_user()
    db.session.delete(usuario)
    db.session.commit()
    return redirect(url_for("registro"))


# =====================================================================
# RF04: Categorias personalizadas del usuario
# Las predefinidas pertenecen al sistema (usuario_id vacio) y las
# personalizadas a quien las creo, que es el unico que las ve y las usa.
# =====================================================================

@app.route("/categorias", methods=["GET", "POST"])
@login_required
def categorias_personalizadas():
    """RF04: lista las categorias disponibles y permite crear propias."""
    error = None
    if request.method == "POST":
        nombre = _texto(request.form.get("nombre"), LARGO_MAXIMO_CATEGORIA)
        if not nombre:
            error = "Escribe un nombre para la categoría."
        else:
            # La comparacion ignora mayusculas y acentos del propio texto
            # para que no convivan "Mascotas" y "mascotas".
            existe = next(
                (c for c in _categorias_disponibles()
                 if c.nombre.strip().lower() == nombre.lower()), None)
            if existe is not None:
                error = f"Ya existe una categoría llamada {existe.nombre}."
            else:
                db.session.add(Categoria(nombre=nombre, es_predefinida=False,
                                         usuario_id=current_user.id))
                db.session.commit()
                return redirect(url_for("categorias_personalizadas"))

    # Cantidad de gastos propios por categoria: sirve para informar al
    # usuario y para decidir si una categoria se puede eliminar.
    usos = dict(db.session.query(Gasto.categoria_id, db.func.count(Gasto.id))
                .filter(Gasto.usuario_id == current_user.id)
                .group_by(Gasto.categoria_id).all())
    return render_template("categorias.html",
                           categorias=_categorias_disponibles(),
                           usos=usos,
                           error=error or request.args.get("error"))


@app.route("/categorias/<int:categoria_id>/eliminar", methods=["POST"])
@login_required
def eliminar_categoria(categoria_id):
    """RF04: elimina una categoria propia.

    Dos salvaguardas: solo se puede borrar una categoria propia (nunca
    las del sistema ni las de otro usuario), y solo si no tiene gastos
    asociados, porque borrarla dejaria esos gastos sin categoria y
    falsearia todos los reportes."""
    categoria = Categoria.query.filter_by(
        id=categoria_id, usuario_id=current_user.id, es_predefinida=False).first_or_404()

    if Gasto.query.filter_by(categoria_id=categoria.id).first():
        return redirect(url_for(
            "categorias_personalizadas",
            error="No se puede eliminar una categoría que ya tiene gastos."))

    # Se quitan primero las asignaciones de presupuesto que la usaban,
    # porque la base de datos ahora exige integridad referencial.
    for detalle in PresupuestoCategoria.query.filter_by(categoria_id=categoria.id).all():
        db.session.delete(detalle)
    db.session.delete(categoria)
    db.session.commit()
    return redirect(url_for("categorias_personalizadas"))


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
        for categoria in _categorias_disponibles():
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
        categorias=_categorias_disponibles(),
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
        grafica_evolucion=reportes.grafica_evolucion(
            datos["evolucion"], localizacion.simbolo(_moneda_del_usuario())),
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
        moneda=_moneda_del_usuario(),
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
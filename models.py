"""
Modelos de datos del Rastreador de Gastos.
Corresponde al DER definido en la seccion 5.2.2 de la Tarea #2.
Cada clase representa una tabla de la base de datos SQLite.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone


def ahora_utc():
    """Marca de tiempo actual en UTC, sin zona horaria.

    Las fechas se GUARDAN siempre en UTC y se CONVIERTEN a la zona del
    usuario al mostrarlas. Es la practica habitual: si se guardara la
    hora local, los datos cambiarian de significado al mover el sistema
    a un servidor de otro pais. La conversion para mostrar vive en el
    filtro fecha_local de app.py.

    Se usa datetime.now(timezone.utc) porque el metodo antiguo quedo
    obsoleto a partir de Python 3.12."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

db = SQLAlchemy()


class Usuario(db.Model, UserMixin):
    """Entidad Usuario. Soporta RF01 (cuentas) y RNF03 (la contrasena
    se guarda hasheada, nunca en texto plano)."""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(120), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=ahora_utc)

    # Preferencias de localizacion del usuario (RNF01). Determinan la
    # moneda en que ve sus montos y la hora en que lee sus fechas, de
    # modo que el sistema sirva fuera de un solo pais. Los valores se
    # validan contra las listas de localizacion.py antes de guardarse.
    pais = db.Column(db.String(60), default="")
    ciudad = db.Column(db.String(80), default="")
    moneda = db.Column(db.String(3), default="USD")
    zona_horaria = db.Column(db.String(60), default="America/Puerto_Rico")

    gastos = db.relationship("Gasto", backref="usuario")
    categorias = db.relationship("Categoria", backref="usuario")


class Categoria(db.Model):
    """Entidad Categoria. Soporta RF04.
    es_predefinida distingue las categorias base del sistema de las que
    crea el propio usuario (usuario_id queda vacio en las predefinidas)."""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(60), nullable=False)
    es_predefinida = db.Column(db.Boolean, default=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)

    gastos = db.relationship("Gasto", backref="categoria")


class Gasto(db.Model):
    """Entidad Gasto, nucleo del sistema. Soporta RF02 y RF03.
    Es la fuente de datos de los reportes (RF06) y del analisis de
    patrones para las recomendaciones (RF08)."""
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, default=lambda: ahora_utc().date())
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200))
    metodo_pago = db.Column(db.String(40))
    categoria_id = db.Column(db.Integer, db.ForeignKey("categoria.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)


class Presupuesto(db.Model):
    """Entidad Presupuesto mensual. Soporta RF05 y sirve de referencia
    para las alertas de RF10."""
    id = db.Column(db.Integer, primary_key=True)
    mes = db.Column(db.Integer, nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    monto_total = db.Column(db.Float, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)

    detalles = db.relationship("PresupuestoCategoria", backref="presupuesto")


class PresupuestoCategoria(db.Model):
    """Detalle del presupuesto por categoria. Soporta RF05.
    La relacion con Categoria permite leer el nombre de la categoria
    directamente desde el detalle (detalle.categoria.nombre) al comparar
    el presupuesto con el gasto real."""
    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey("presupuesto.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categoria.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)

    categoria = db.relationship("Categoria")


class Recomendacion(db.Model):
    """Historial de recomendaciones de ahorro. Soporta RF08.
    El campo aplicada permite medir en la validacion si el usuario
    cambia su conducta, segun la seccion 5.3.5 de la Tarea #2."""
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=ahora_utc)
    texto = db.Column(db.Text, nullable=False)
    ahorro_estimado = db.Column(db.Float)
    aplicada = db.Column(db.Boolean, default=False)
    # Nivel que genero la recomendacion: "ia" o "reglas". Permite comparar
    # la calidad de los dos niveles durante la validacion del proyecto.
    origen = db.Column(db.String(20), default="reglas")
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
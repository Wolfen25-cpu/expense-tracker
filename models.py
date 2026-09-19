from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(120), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    gastos = db.relationship("Gasto", backref="usuario")
    categorias = db.relationship("Categoria", backref="usuario")

class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(60), nullable=False)
    es_predefinida = db.Column(db.Boolean, default=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)

    gastos = db.relationship("Gasto", backref="categoria")

class Gasto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200))
    metodo_pago = db.Column(db.String(40))
    categoria_id = db.Column(db.Integer, db.ForeignKey("categoria.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)

class Presupuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mes = db.Column(db.Integer, nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    monto_total = db.Column(db.Float, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)

    detalles = db.relationship("PresupuestoCategoria", backref="presupuesto")

class PresupuestoCategoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey("presupuesto.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categoria.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)

class Recomendacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    texto = db.Column(db.Text, nullable=False)
    ahorro_estimado = db.Column(db.Float)
    aplicada = db.Column(db.Boolean, default=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
from flask import Flask
from models import db, Categoria

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///gastos.db"
app.config["SECRET_KEY"] = "clave-temporal-de-desarrollo"
db.init_app(app)

CATEGORIAS_BASE = ["Alimentación", "Transporte", "Vivienda", "Salud",
                   "Entretenimiento", "Educación", "Otros"]

@app.route("/")
def inicio():
    categorias = Categoria.query.filter_by(es_predefinida=True).all()
    lista = "".join(f"<li>{c.nombre}</li>" for c in categorias)
    return f"<h1>Rastreador de Gastos</h1><p>Categorías en la base de datos:</p><ul>{lista}</ul>"

with app.app_context():
    db.create_all()
    if not Categoria.query.filter_by(es_predefinida=True).first():
        for nombre in CATEGORIAS_BASE:
            db.session.add(Categoria(nombre=nombre, es_predefinida=True))
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=True)
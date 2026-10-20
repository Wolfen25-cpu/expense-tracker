from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Usuario, Categoria

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///gastos.db"
app.config["SECRET_KEY"] = "clave-temporal-de-desarrollo"
db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))

CATEGORIAS_BASE = ["Alimentación", "Transporte", "Vivienda", "Salud",
                   "Entretenimiento", "Educación", "Otros"]

@app.route("/registro", methods=["GET", "POST"])
def registro():
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
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def inicio():
    categorias = Categoria.query.filter_by(es_predefinida=True).all()
    lista = "".join(f"<li>{c.nombre}</li>" for c in categorias)
    return (f"<h1>Hola, {current_user.nombre}</h1>"
            f"<p>Categorías disponibles:</p><ul>{lista}</ul>"
            f"<p><a href='/logout'>Cerrar sesión</a></p>")

with app.app_context():
    db.create_all()
    if not Categoria.query.filter_by(es_predefinida=True).first():
        for nombre in CATEGORIAS_BASE:
            db.session.add(Categoria(nombre=nombre, es_predefinida=True))
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=True)
from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime
from models import db, Usuario, Categoria, Gasto

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
                   "Entretenimiento", "Educación", "Mensualidades", "Otros"]

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
    return redirect(url_for("gastos"))

@app.route("/gastos", methods=["GET", "POST"])
@login_required
def gastos():
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

@app.route("/gastos/<int:gasto_id>/editar", methods=["GET", "POST"])
@login_required
def editar_gasto(gasto_id):
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
    gasto = Gasto.query.filter_by(id=gasto_id, usuario_id=current_user.id).first_or_404()
    db.session.delete(gasto)
    db.session.commit()
    return redirect(url_for("gastos"))

with app.app_context():
    db.create_all()
    for nombre in CATEGORIAS_BASE:
        if not Categoria.query.filter_by(nombre=nombre, es_predefinida=True).first():
            db.session.add(Categoria(nombre=nombre, es_predefinida=True))
    db.session.commit()

if __name__ == "__main__":
    app.run(debug=True)
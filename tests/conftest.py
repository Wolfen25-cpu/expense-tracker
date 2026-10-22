"""
Configuracion comun de las pruebas (estrategia de pruebas de software).

Las pruebas usan una base de datos SQLite en memoria. La variable de
entorno GASTOS_DB se define ANTES de importar app, asi que nunca se toca
el archivo instance/gastos.db con los datos reales del usuario.
"""

import os

os.environ["GASTOS_DB"] = "sqlite:///:memory:"

import pytest

from app import app, db, Categoria, CATEGORIAS_BASE


@pytest.fixture
def cliente():
    """Cliente de pruebas con una base de datos limpia en cada prueba:
    se recrean las tablas y se cargan las categorias predefinidas."""
    app.config["TESTING"] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
        for nombre in CATEGORIAS_BASE:
            db.session.add(Categoria(nombre=nombre, es_predefinida=True))
        db.session.commit()
        yield app.test_client()
        db.session.remove()


def registrar(cliente, nombre="Ana", correo="ana@ejemplo.com", contrasena="clave123"):
    """Crea una cuenta y deja la sesion iniciada en ese cliente."""
    return cliente.post("/registro", data={
        "nombre": nombre, "correo": correo, "contrasena": contrasena,
    })


def crear_gasto(cliente, fecha="2026-10-15", monto="25.50", categoria_id=1,
                descripcion="Prueba", metodo_pago="Efectivo"):
    """Registra un gasto con el usuario que tenga la sesion iniciada."""
    return cliente.post("/gastos", data={
        "fecha": fecha, "monto": monto, "categoria_id": categoria_id,
        "descripcion": descripcion, "metodo_pago": metodo_pago,
    })

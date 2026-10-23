"""
Generador de datos de prueba del Rastreador de Gastos.
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Crea una cuenta de demostracion con tres meses de gastos realistas y sus
presupuestos. Sirve para probar los reportes, las graficas y las
recomendaciones sin tener que registrar decenas de gastos a mano, y para
las demostraciones ante el profesor y el panel de expertos.

Uso, con el entorno virtual activo:

    python datos_prueba.py

Los datos se generan de forma deliberada para que se vean todas las
funciones del sistema:

  * Suscripciones que se repiten los tres meses, con la misma
    descripcion y el mismo monto, para que el detector de gastos
    recurrentes las encuentre (RF08).
  * Una categoria que crece de forma marcada en el mes actual, para
    disparar la regla de crecimiento (RF08).
  * Una categoria que se pasa del presupuesto del mes actual, para
    disparar la alerta y la regla correspondiente (RF10).

SEGURIDAD: el script solo toca la cuenta de demostracion definida en
CORREO_DEMO. Los datos de cualquier otra cuenta quedan intactos. Al
volver a ejecutarlo se borran y se vuelven a crear solo los gastos y
presupuestos de esa cuenta, para que el resultado sea siempre el mismo.
"""

import random
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from app import app
from models import (db, Usuario, Categoria, Gasto,
                    Presupuesto, PresupuestoCategoria)
import presupuesto as modulo_presupuesto

# ---------------------------------------------------------------------
# Configuracion de la cuenta de demostracion
# ---------------------------------------------------------------------
NOMBRE_DEMO = "Usuario de Demostración"
CORREO_DEMO = "demo@ejemplo.com"
CLAVE_DEMO = "demo1234"

MESES_A_GENERAR = 3

# La semilla fija hace que los montos aleatorios sean siempre los mismos.
# Una demostracion debe poder repetirse con identicos resultados.
SEMILLA = 6970

# Gastos fijos que se repiten todos los meses. La descripcion importa:
# el detector de recurrentes agrupa por categoria, monto y descripcion,
# de modo que dos servicios de igual precio no se confundan entre si.
GASTOS_FIJOS = [
    ("Vivienda", "Alquiler", 650.00, 1),
    ("Mensualidades", "Teléfono", 45.00, 5),
    ("Mensualidades", "Internet", 39.99, 8),
    ("Mensualidades", "Streaming", 12.99, 12),
    ("Vivienda", "Energía eléctrica", 118.00, 15),
]

# Gastos variables: categoria, descripciones posibles, rango de monto,
# y cuantas veces aparecen en el mes.
GASTOS_VARIABLES = [
    ("Alimentación", ["Supermercado", "Colmado", "Almuerzo", "Panadería"], 22, 95, 5),
    ("Transporte", ["Gasolina", "Peaje", "Estacionamiento"], 15, 55, 3),
    ("Salud", ["Farmacia", "Copago médico"], 12, 45, 1),
    ("Entretenimiento", ["Cine", "Restaurante", "Salida"], 18, 60, 2),
    ("Educación", ["Libro", "Materiales"], 20, 70, 1),
    ("Otros", ["Regalo", "Ferretería", "Varios"], 10, 40, 1),
]

METODOS = ["Efectivo", "Tarjeta de débito", "Tarjeta de crédito", "Transferencia"]

# Presupuesto mensual por categoria. Alimentación queda ajustado a
# proposito para que el mes actual lo supere y se vea la alerta (RF10).
PRESUPUESTO_TOTAL = 1500.00
PRESUPUESTO_CATEGORIAS = {
    "Vivienda": 800.00,
    "Alimentación": 300.00,
    "Transporte": 150.00,
    "Mensualidades": 120.00,
    "Entretenimiento": 100.00,
    "Salud": 60.00,
}


def _primer_dia(desplazamiento):
    """Primer dia del mes desplazado respecto al mes actual."""
    hoy = date.today()
    mes, anio = modulo_presupuesto.mes_desplazado(hoy.month, hoy.year, desplazamiento)
    return date(anio, mes, 1)


def _dia_valido(inicio_mes, dia):
    """Evita fechas inexistentes, como el 31 en un mes de 30 dias, y no
    genera gastos en el futuro dentro del mes en curso."""
    siguiente = (inicio_mes + timedelta(days=32)).replace(day=1)
    ultimo = (siguiente - timedelta(days=1)).day
    fecha = inicio_mes.replace(day=min(dia, ultimo))
    return min(fecha, date.today())


def obtener_usuario():
    """Devuelve la cuenta de demostracion, creandola si hace falta."""
    usuario = Usuario.query.filter_by(correo=CORREO_DEMO).first()
    if usuario is None:
        usuario = Usuario(nombre=NOMBRE_DEMO, correo=CORREO_DEMO,
                          contrasena_hash=generate_password_hash(CLAVE_DEMO))
        db.session.add(usuario)
        db.session.commit()
        print(f"Cuenta creada: {CORREO_DEMO} / {CLAVE_DEMO}")
    else:
        print(f"Cuenta existente: {CORREO_DEMO}")
    return usuario


def limpiar(usuario):
    """Borra los gastos y presupuestos previos de la cuenta de
    demostracion para que el script se pueda repetir sin acumular datos."""
    gastos = Gasto.query.filter_by(usuario_id=usuario.id).all()
    presupuestos = Presupuesto.query.filter_by(usuario_id=usuario.id).all()
    for p in presupuestos:
        for detalle in list(p.detalles):
            db.session.delete(detalle)
        db.session.delete(p)
    for g in gastos:
        db.session.delete(g)
    db.session.commit()
    print(f"Datos anteriores eliminados: {len(gastos)} gastos, "
          f"{len(presupuestos)} presupuestos")


def crear_gastos(usuario, categorias):
    """Genera los gastos de los ultimos meses."""
    azar = random.Random(SEMILLA)
    creados = 0

    for desplazamiento in range(-(MESES_A_GENERAR - 1), 1):
        inicio = _primer_dia(desplazamiento)
        es_mes_actual = desplazamiento == 0

        # Gastos fijos: mismo monto y misma descripcion cada mes, que es
        # lo que convierte a una suscripcion en un gasto recurrente.
        for categoria, descripcion, monto, dia in GASTOS_FIJOS:
            db.session.add(Gasto(
                fecha=_dia_valido(inicio, dia),
                monto=monto,
                descripcion=descripcion,
                metodo_pago="Transferencia",
                categoria_id=categorias[categoria],
                usuario_id=usuario.id,
            ))
            creados += 1

        # Gastos variables
        for categoria, descripciones, minimo, maximo, veces in GASTOS_VARIABLES:
            repeticiones = veces
            factor = 1.0
            # En el mes actual se aumenta Entretenimiento a proposito
            # para que la regla de crecimiento tenga algo que detectar,
            # y Alimentación para que supere su presupuesto.
            if es_mes_actual and categoria == "Entretenimiento":
                repeticiones, factor = veces + 2, 1.5
            if es_mes_actual and categoria == "Alimentación":
                factor = 1.35

            for _ in range(repeticiones):
                monto = round(azar.uniform(minimo, maximo) * factor, 2)
                db.session.add(Gasto(
                    fecha=_dia_valido(inicio, azar.randint(2, 28)),
                    monto=monto,
                    descripcion=azar.choice(descripciones),
                    metodo_pago=azar.choice(METODOS),
                    categoria_id=categorias[categoria],
                    usuario_id=usuario.id,
                ))
                creados += 1

    db.session.commit()
    return creados


def crear_presupuestos(usuario, categorias):
    """Define el mismo presupuesto para cada uno de los meses generados."""
    creados = 0
    for desplazamiento in range(-(MESES_A_GENERAR - 1), 1):
        inicio = _primer_dia(desplazamiento)
        registro = Presupuesto(mes=inicio.month, anio=inicio.year,
                               monto_total=PRESUPUESTO_TOTAL,
                               usuario_id=usuario.id)
        db.session.add(registro)
        for nombre, monto in PRESUPUESTO_CATEGORIAS.items():
            db.session.add(PresupuestoCategoria(
                presupuesto=registro, categoria_id=categorias[nombre], monto=monto))
        creados += 1
    db.session.commit()
    return creados


def main():
    with app.app_context():
        categorias = {c.nombre: c.id
                      for c in Categoria.query.filter_by(es_predefinida=True).all()}
        faltantes = [n for n, _, _, _ in GASTOS_FIJOS if n not in categorias]
        if faltantes:
            print("Faltan categorias predefinidas:", faltantes)
            return

        usuario = obtener_usuario()
        limpiar(usuario)
        gastos = crear_gastos(usuario, categorias)
        presupuestos = crear_presupuestos(usuario, categorias)

        total = sum(g.monto for g in Gasto.query.filter_by(usuario_id=usuario.id).all())
        print(f"Gastos creados: {gastos}")
        print(f"Presupuestos creados: {presupuestos}")
        print(f"Total registrado: ${total:,.2f}")
        print()
        print("Entra con estas credenciales para ver los datos:")
        print(f"  Correo:     {CORREO_DEMO}")
        print(f"  Contraseña: {CLAVE_DEMO}")


if __name__ == "__main__":
    main()

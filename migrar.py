"""
Migracion del esquema de la base de datos.
COMP 6970: Seminario Integrador

SQLAlchemy crea las tablas que faltan, pero nunca modifica una tabla que
ya existe. Cuando el modelo gana una columna nueva, las bases de datos
creadas antes se quedan sin ella y la aplicacion falla al arrancar.

Este script compara las columnas que la base tiene con las que deberia
tener y agrega unicamente las que faltan. Es idempotente: se puede
ejecutar las veces que haga falta y no hace nada si ya esta todo al dia.

Uso, con el entorno virtual activo:

    python migrar.py

En un proyecto de mayor tamano esta tarea se delega a una herramienta de
migraciones como Alembic o Flask-Migrate, que ademas lleva el historial
de cada cambio y permite deshacerlo. Esta version cumple la misma
funcion a la escala de este prototipo.
"""

import os
import sqlite3

# Columnas que debe tener cada tabla, con su definicion en SQL.
# Al agregar una columna nueva al modelo, se anade aqui tambien.
COLUMNAS_ESPERADAS = {
    "usuario": {
        "pais": "VARCHAR(60) DEFAULT ''",
        "ciudad": "VARCHAR(80) DEFAULT ''",
        "moneda": "VARCHAR(3) DEFAULT 'USD'",
        "zona_horaria": "VARCHAR(60) DEFAULT 'America/Puerto_Rico'",
    },
    "recomendacion": {
        "origen": "VARCHAR(20) DEFAULT 'reglas'",
    },
}


def ruta_base_de_datos():
    """Deduce el archivo de la base a partir de la misma variable de
    entorno que usa la aplicacion."""
    uri = os.environ.get("GASTOS_DB", "sqlite:///gastos.db")
    nombre = uri.replace("sqlite:///", "")
    if not os.path.isabs(nombre):
        nombre = os.path.join("instance", nombre)
    return nombre


def columnas_actuales(conexion, tabla):
    return {fila[1] for fila in conexion.execute(f"PRAGMA table_info({tabla})")}


def tabla_existe(conexion, tabla):
    consulta = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
    return conexion.execute(consulta, (tabla,)).fetchone() is not None


def main():
    archivo = ruta_base_de_datos()
    if not os.path.exists(archivo):
        print(f"No existe {archivo}. Arranca la aplicación una vez para crearla.")
        return

    conexion = sqlite3.connect(archivo)
    agregadas = 0
    for tabla, columnas in COLUMNAS_ESPERADAS.items():
        if not tabla_existe(conexion, tabla):
            print(f"La tabla {tabla} todavía no existe, se omite.")
            continue
        existentes = columnas_actuales(conexion, tabla)
        for columna, definicion in columnas.items():
            if columna in existentes:
                continue
            conexion.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
            print(f"Agregada: {tabla}.{columna}")
            agregadas += 1
    conexion.commit()
    conexion.close()

    if agregadas:
        print(f"Migración completada: {agregadas} columna(s) agregada(s).")
    else:
        print("La base de datos ya estaba al día.")


if __name__ == "__main__":
    main()

"""
Pruebas de las categorias personalizadas (RF04).

El requisito pide categorias predefinidas Y personalizadas. Estas
pruebas cubren la creacion, el uso, las reglas de eliminacion y la
privacidad entre cuentas.
"""

from datetime import date

from conftest import registrar, crear_gasto


def test_se_listan_las_categorias_del_sistema(cliente):
    registrar(cliente)
    pagina = cliente.get("/categorias").get_data(as_text=True)
    assert "Alimentación" in pagina
    assert "Del sistema" in pagina


def test_crear_una_categoria_propia(cliente):
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    pagina = cliente.get("/categorias").get_data(as_text=True)
    assert "Veterinario" in pagina
    assert "Personalizada" in pagina


def test_la_categoria_propia_sirve_para_registrar_gastos(cliente):
    """De nada vale crearla si despues no aparece en el formulario."""
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    assert "Veterinario" in cliente.get("/gastos").get_data(as_text=True)
    assert "Veterinario" in cliente.get("/presupuesto").get_data(as_text=True)


def test_no_se_permiten_nombres_repetidos(cliente):
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    respuesta = cliente.post("/categorias", data={"nombre": "veterinario"},
                             follow_redirects=True)
    assert "Ya existe" in respuesta.get_data(as_text=True)


def test_no_se_permite_repetir_una_categoria_del_sistema(cliente):
    registrar(cliente)
    respuesta = cliente.post("/categorias", data={"nombre": "Alimentación"},
                             follow_redirects=True)
    assert "Ya existe" in respuesta.get_data(as_text=True)


def test_el_nombre_vacio_se_rechaza(cliente):
    registrar(cliente)
    respuesta = cliente.post("/categorias", data={"nombre": "   "},
                             follow_redirects=True)
    assert "nombre" in respuesta.get_data(as_text=True).lower()


def test_eliminar_una_categoria_propia_sin_gastos(cliente):
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    pagina = cliente.get("/categorias").get_data(as_text=True)
    identificador = pagina.split("/categorias/")[1].split("/")[0]
    cliente.post(f"/categorias/{identificador}/eliminar", follow_redirects=True)
    assert "Veterinario" not in cliente.get("/categorias").get_data(as_text=True)


def test_no_se_elimina_una_categoria_con_gastos(cliente):
    """Borrarla dejaria esos gastos sin categoria y los reportes
    quedarian falseados."""
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    pagina = cliente.get("/categorias").get_data(as_text=True)
    identificador = int(pagina.split("/categorias/")[1].split("/")[0])
    crear_gasto(cliente, fecha=date.today().isoformat(), categoria_id=identificador)
    respuesta = cliente.post(f"/categorias/{identificador}/eliminar",
                             follow_redirects=True)
    assert "No se puede eliminar" in respuesta.get_data(as_text=True)
    assert "Veterinario" in cliente.get("/categorias").get_data(as_text=True)


def test_no_se_pueden_eliminar_las_del_sistema(cliente):
    """Las categorias predefinidas pertenecen al sistema, no al usuario."""
    registrar(cliente)
    assert cliente.post("/categorias/1/eliminar").status_code == 404


def test_no_se_puede_eliminar_la_categoria_de_otro(cliente):
    registrar(cliente)
    cliente.post("/categorias", data={"nombre": "Veterinario"})
    pagina = cliente.get("/categorias").get_data(as_text=True)
    identificador = pagina.split("/categorias/")[1].split("/")[0]
    cliente.post("/logout")
    registrar(cliente, nombre="Luis", correo="luis@ejemplo.com", contrasena="clave456")
    assert cliente.post(f"/categorias/{identificador}/eliminar").status_code == 404


def test_las_categorias_requieren_sesion(cliente):
    respuesta = cliente.get("/categorias")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]

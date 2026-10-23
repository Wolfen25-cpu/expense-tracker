"""
Modulo de localizacion del Rastreador de Gastos.
COMP 6970: Seminario Integrador
Universidad Interamericana de Puerto Rico, Recinto de Fajardo

Concentra todo lo que depende del pais del usuario: la moneda en que se
muestran los montos, la zona horaria en que se leen las fechas y la
lista de paises. Tenerlo en un solo modulo evita que el simbolo de
dolar quede escrito a mano en cada plantilla, que es lo que impedia
usar el sistema fuera de Estados Unidos y Puerto Rico.

Requisitos que soporta:
  RNF01 usabilidad: cada usuario ve los montos en su propia moneda y las
        fechas en su propia hora.
  RNF05 mantenibilidad: agregar una moneda nueva es anadir una linea a
        un diccionario, sin tocar ninguna plantilla.
"""

# ---------------------------------------------------------------------
# Monedas
# estilo "americano"  1,234.56   coma para miles y punto para decimales
# estilo "europeo"    1.234,56   al reves
# antes=True          el simbolo va delante del numero
# ---------------------------------------------------------------------
MONEDAS = {
    "USD": {"nombre": "Dólar estadounidense", "simbolo": "$", "antes": True, "estilo": "americano"},
    "EUR": {"nombre": "Euro", "simbolo": "€", "antes": False, "estilo": "europeo"},
    "MXN": {"nombre": "Peso mexicano", "simbolo": "$", "antes": True, "estilo": "americano"},
    "DOP": {"nombre": "Peso dominicano", "simbolo": "RD$", "antes": True, "estilo": "americano"},
    "COP": {"nombre": "Peso colombiano", "simbolo": "$", "antes": True, "estilo": "europeo"},
    "ARS": {"nombre": "Peso argentino", "simbolo": "$", "antes": True, "estilo": "europeo"},
    "CLP": {"nombre": "Peso chileno", "simbolo": "$", "antes": True, "estilo": "europeo"},
    "PEN": {"nombre": "Sol peruano", "simbolo": "S/", "antes": True, "estilo": "americano"},
    "BOB": {"nombre": "Boliviano", "simbolo": "Bs", "antes": True, "estilo": "americano"},
    "BRL": {"nombre": "Real brasileño", "simbolo": "R$", "antes": True, "estilo": "europeo"},
    "GBP": {"nombre": "Libra esterlina", "simbolo": "£", "antes": True, "estilo": "americano"},
    "CAD": {"nombre": "Dólar canadiense", "simbolo": "C$", "antes": True, "estilo": "americano"},
    "GTQ": {"nombre": "Quetzal guatemalteco", "simbolo": "Q", "antes": True, "estilo": "americano"},
    "CRC": {"nombre": "Colón costarricense", "simbolo": "₡", "antes": True, "estilo": "europeo"},
    "UYU": {"nombre": "Peso uruguayo", "simbolo": "$U", "antes": True, "estilo": "europeo"},
}

MONEDA_POR_DEFECTO = "USD"

# ---------------------------------------------------------------------
# Zonas horarias
# Se ofrece una lista corta y util en lugar de las mas de seiscientas
# que conoce el sistema: una lista interminable no ayuda a elegir.
# ---------------------------------------------------------------------
ZONAS_HORARIAS = [
    "America/Puerto_Rico",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Mexico_City",
    "America/Bogota",
    "America/Lima",
    "America/La_Paz",
    "America/Santiago",
    "America/Argentina/Buenos_Aires",
    "America/Sao_Paulo",
    "America/Santo_Domingo",
    "America/Guatemala",
    "America/Costa_Rica",
    "America/Montevideo",
    "America/Toronto",
    "Europe/Madrid",
    "Europe/London",
    "UTC",
]

ZONA_POR_DEFECTO = "America/Puerto_Rico"

# ---------------------------------------------------------------------
# Paises. Cada uno sugiere su moneda y su zona horaria, que es lo que
# la mayoria de la gente querria y ahorra tener que elegir tres veces.
# ---------------------------------------------------------------------
PAISES = {
    "Puerto Rico": ("USD", "America/Puerto_Rico"),
    "Estados Unidos": ("USD", "America/New_York"),
    "México": ("MXN", "America/Mexico_City"),
    "República Dominicana": ("DOP", "America/Santo_Domingo"),
    "Colombia": ("COP", "America/Bogota"),
    "Perú": ("PEN", "America/Lima"),
    "Bolivia": ("BOB", "America/La_Paz"),
    "Chile": ("CLP", "America/Santiago"),
    "Argentina": ("ARS", "America/Argentina/Buenos_Aires"),
    "Uruguay": ("UYU", "America/Montevideo"),
    "Brasil": ("BRL", "America/Sao_Paulo"),
    "Guatemala": ("GTQ", "America/Guatemala"),
    "Costa Rica": ("CRC", "America/Costa_Rica"),
    "España": ("EUR", "Europe/Madrid"),
    "Reino Unido": ("GBP", "Europe/London"),
    "Canadá": ("CAD", "America/Toronto"),
    "Otro": ("USD", "UTC"),
}


# ---------------------------------------------------------------------
# Formato de montos
# ---------------------------------------------------------------------
def simbolo(codigo):
    """Simbolo de la moneda, con el dolar como respaldo si el codigo no
    se reconoce."""
    return MONEDAS.get(codigo, MONEDAS[MONEDA_POR_DEFECTO])["simbolo"]


def formatear(valor, codigo=MONEDA_POR_DEFECTO):
    """Convierte un numero en un monto legible segun la moneda elegida.

    El signo negativo se coloca delante de todo ("-$25.00" y no
    "$-25.00"), que es como se lee de forma natural.
    """
    info = MONEDAS.get(codigo, MONEDAS[MONEDA_POR_DEFECTO])
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        numero = 0.0

    signo = "-" if numero < 0 else ""
    texto = f"{abs(numero):,.2f}"
    if info["estilo"] == "europeo":
        # Se intercambian los separadores usando una marca temporal para
        # no pisar el resultado a medio camino.
        texto = texto.replace(",", "|").replace(".", ",").replace("|", ".")

    if info["antes"]:
        return f"{signo}{info['simbolo']}{texto}"
    return f"{signo}{texto} {info['simbolo']}"


def moneda_valida(codigo):
    """Codigo de moneda admitido, o el de respaldo (RNF03: nunca se
    guarda en la base un valor que no este en la lista)."""
    return codigo if codigo in MONEDAS else MONEDA_POR_DEFECTO


def zona_valida(nombre):
    """Zona horaria admitida, o la de respaldo."""
    return nombre if nombre in ZONAS_HORARIAS else ZONA_POR_DEFECTO


def pais_valido(nombre):
    """Pais admitido, o cadena vacia si no se reconoce."""
    return nombre if nombre in PAISES else ""

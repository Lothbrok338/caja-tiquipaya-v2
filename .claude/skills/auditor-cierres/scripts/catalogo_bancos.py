"""catalogo_bancos.py — Tabla oficial BANCO <-> CUENTA CONTABLE (unica fuente de verdad)
y familias de banco para el formato de ASIGNACION.

Solo datos y funciones puras; no lee archivos.
"""
from xlsm_xml import normalizar_texto

# (cuenta contable, descripcion, nombre corto tal como se escribe en BANCO)
TABLA_OFICIAL = [
    ("110103012", "BNB MN 3000100152", "BNB MN"),
    ("110103022", "BNB MN 3000100705", "BNB CLINICA"),
    ("110103032", "BISA MN 696870039", "BISA MN"),
    ("110103042", "BCP MN 3015005684397", "BCP MN"),
    ("110103052", "BUSA MN 13224552", "BUSA MN"),
    ("110103062", "BANECO MN 3041210569", "BANECO"),
    ("110103072", "BMS MN 4010879042", "BMS"),
    ("110104012", "BNB ME 3400041236", "BNB ME"),
    ("110104022", "BISA ME 696872023", "BISA ME"),
    ("110104032", "BCP ME 3015005425271", "BCP ME"),
    ("110104042", "BUSA ME 23224544", "BUSA ME"),
    ("110103722", "BANECO MN A AH 3051446946", "BANECO AH"),
    ("110105112", "BISA EURO A AH 0696876517", "BISA EURO"),
    ("110103712", "BNB MN A AH 3501936692", "BNB AH"),
]
CUENTA_POR_CLAVE = {corto: cuenta for cuenta, _d, corto in TABLA_OFICIAL}

# Categorias especiales que se escriben en la columna BANCO (no son bancos).
ESPECIALES = ("OTROS INGRESOS", "GASTO.ADM", "ALQUILERES", "POSGRADO.PLA")
_ESPECIALES_NORM = {normalizar_texto(e): e for e in ESPECIALES}

# Alias aceptados al interpretar el texto de BANCO.
_ALIAS = (("BANCO ECONOMICO", "BANECO"), ("BANCO UNION", "BUSA"), ("BMSC", "BMS"))
FAMILIAS = ("BNB", "BISA", "BCP", "BUSA", "BANECO", "BMS")
# Familias cuya clave "sin sufijo" en la tabla ya es la moneda nacional.
_SIN_SUFIJO_YA_ES_MN = ("BANECO", "BMS")

FORMATO_ASIGNACION = {
    "BANECO": "NUMERICO", "BUSA": "NUMERICO", "BCP": "NUMERICO", "BISA": "NUMERICO",
    "BMS": "ALFANUMERICO", "BNB": "ALFANUMERICO",
}


def categoria_especial(texto):
    """Nombre canonico de la categoria especial, o None."""
    return _ESPECIALES_NORM.get(normalizar_texto(texto))


def interpretar_banco(texto):
    """Interpreta el texto de BANCO.

    Devuelve dict: familia, sufijo, clave, cuenta_esperada, estado.
    estado: OK | SUFIJO_NO_RECONOCIDO (familia conocida, combinacion fuera de
    la tabla) | BANCO_NO_RECONOCIDO.
    Sin sufijo se asume MN (decision del usuario) salvo BANECO/BMS, cuya clave
    de tabla ya es MN. MN explicito en BANECO/BMS equivale a la clave sola."""
    norm = normalizar_texto(texto)
    for alias, fam in _ALIAS:
        if norm == alias or norm.startswith(alias + " "):
            norm = fam + norm[len(alias):]
            break
    tokens = norm.split()
    if not tokens or tokens[0] not in FAMILIAS:
        return {"familia": None, "sufijo": None, "clave": None, "cuenta_esperada": None,
                "estado": "BANCO_NO_RECONOCIDO"}
    familia, sufijo = tokens[0], " ".join(tokens[1:])
    if sufijo == "":
        clave = familia if familia in _SIN_SUFIJO_YA_ES_MN else familia + " MN"
    elif sufijo == "MN" and familia in _SIN_SUFIJO_YA_ES_MN:
        clave = familia
    else:
        clave = familia + " " + sufijo
    cuenta = CUENTA_POR_CLAVE.get(clave)
    return {"familia": familia, "sufijo": sufijo, "clave": clave, "cuenta_esperada": cuenta,
            "estado": "OK" if cuenta else "SUFIJO_NO_RECONOCIDO"}


def formato_valido(asignacion, esperado):
    """NUMERICO: solo digitos (se ignoran espacios y guiones).
    ALFANUMERICO: contiene al menos una letra. (Mismas definiciones que usa el
    motor de CAJAS GABO.)"""
    if esperado == "NUMERICO":
        compacto = asignacion.replace(" ", "").replace("-", "")
        return compacto.isdigit()
    return any(ch.isalpha() for ch in asignacion)

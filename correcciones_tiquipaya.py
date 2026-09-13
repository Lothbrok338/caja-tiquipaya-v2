"""
correcciones_tiquipaya.py — FASE 3, Parte B (ver HANDOFF_CODE_V2.md sección
16): validación y aplicación EN MEMORIA de una corrección autorizada por el
auditor sobre una excepción ya detectada por el motor (excepciones[], FASE 1).

No implementa agentes de IA, no permite correcciones automáticas sin
decisión humana explícita (la corrección siempre llega ya decidida, en el
schema de abajo, desde fuera de este módulo) y no cambia ninguna regla
contable: motor_tiquipaya.py y excel_io.py NO se modifican ni se enteran de
que existe una corrección — este módulo solo produce, a partir de una copia
profunda de lo que excel_io.py ya leyó del .xlsm, los MISMOS datos en
memoria que produciría un .xlsm corregido. El .xlsm original nunca se abre
en modo escritura y nunca se modifica.

Campos corregibles por categoría (todo lo demás queda fuera de alcance;
los importes NUNCA son corregibles):

  COMUNICACION_INTERNA: cuenta_contable, asignacion
  VOUCHER:              codigo_informado (solo eligiendo uno de los
                         `candidatos` que el propio motor ya propuso)
  ATC:                  neto_cuenta_contable, neto_asignacion,
                         comision_cuenta_contable, comision_asignacion
                         (solo disponible en modo PRECONCILIADO — hoja
                         "ATC TIQUIPAYA" — porque el modo LEGADO no trae
                         esas columnas)

Schema de una corrección formal (ver HANDOFF_CODE_V2.md §16.3):

{
  "fecha_cierre": "YYYY-MM-DD",
  "sha256_origen": "<sha256 del .xlsm original>",
  "categoria": "COMUNICACION_INTERNA" | "VOUCHER" | "ATC",
  "tipo": "<código técnico original de la excepción>",
  "identificadores": {...},   # forma según categoría, ver más abajo
  "campo_corregido": "...",
  "valor_original": ... | null,
  "valor_autorizado": "...",
  "motivo": "...",
  "usuario_auditor": "...",
  "fecha_hora": "ISO8601",
  "version_correccion": "<sha256 de categoria+tipo+identificadores+campo_corregido+valor_autorizado>"
}

Forma de `identificadores` por categoría (deriva del propio excepciones[]
de FASE 1, ver motor_tiquipaya._excepciones_ci/_excepciones_voucher):

  COMUNICACION_INTERNA: {"sfc": "SFC101", "factura": "..."}
      -> localiza en cierre["comunicaciones_internas"] por sfc+referencia.
  VOUCHER: {"sfc": "SFC101", "codigo_informado": "..."}
      -> localiza el depósito por sfc + el código informado tal cual
         viene en cierre["sfcXXX"]["depositos"][i]["asignacion"].
  ATC: {} (no hace falta nada más: solo existe una fila ATC por cierre,
         ya identificada por el propio `fecha_cierre` de la corrección)
      -> localiza atc_idx["por_fecha"][fecha_cierre].

Toda corrección se valida contra el estado ACTUAL antes de aplicarse:
schema, versión, sha256 del .xlsm, existencia univoca del registro y (para
VOUCHER) que `valor_autorizado` sea uno de los candidatos que el motor ya
propuso. Si cualquier validación falla, no se aplica nada (todo o nada) y
se lanza ValueError con un código de error legible: "CODIGO:detalle" (mismo
patrón que pipeline_tiquipaya.construir_marcador_procesado).
"""

import hashlib
import json
from copy import deepcopy

import motor_tiquipaya as motor


# ---------------------------------------------------------------------------
# Categorías y campos corregibles
# ---------------------------------------------------------------------------

CATEGORIA_CI = "COMUNICACION_INTERNA"
CATEGORIA_VOUCHER = "VOUCHER"
CATEGORIA_ATC = "ATC"

CAMPOS_CORREGIBLES = {
    CATEGORIA_CI: {"cuenta_contable", "asignacion"},
    CATEGORIA_VOUCHER: {"codigo_informado"},
    CATEGORIA_ATC: {
        "neto_cuenta_contable", "neto_asignacion",
        "comision_cuenta_contable", "comision_asignacion",
    },
}

# Mapa campo_corregido (schema ATC, nombres expuestos en excepciones[]) ->
# (sub-registro, campo interno) dentro de atc_idx["por_fecha"][fecha].
_MAPA_CAMPO_ATC = {
    "neto_cuenta_contable": ("neto", "cuenta_contable"),
    "neto_asignacion": ("neto", "asignacion"),
    "comision_cuenta_contable": ("comision", "cuenta_contable"),
    "comision_asignacion": ("comision", "asignacion"),
}

# Campos que entran al cálculo determinístico de version_correccion. El
# orden no importa (se serializa con sort_keys=True), pero la LISTA sí:
# agregar/quitar un campo aquí cambia el hash de toda corrección futura.
_CAMPOS_VERSION = ("categoria", "tipo", "identificadores", "campo_corregido", "valor_autorizado")

_CAMPOS_OBLIGATORIOS = _CAMPOS_VERSION + (
    "fecha_cierre", "sha256_origen", "valor_original", "motivo",
    "usuario_auditor", "fecha_hora", "version_correccion",
)


# ---------------------------------------------------------------------------
# version_correccion — SHA256 determinístico de los 5 campos que definen
# UNIVOCAMENTE qué se está corrigiendo (nunca de motivo/usuario/fecha_hora,
# que son metadata de auditoría, no la decisión en sí).
# ---------------------------------------------------------------------------

def calcular_version_correccion(correccion):
    payload = {campo: correccion.get(campo) for campo in _CAMPOS_VERSION}
    canonico = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def calcular_sha256_archivo(ruta_archivo):
    """SHA256 exacto de un archivo. Duplica intencionalmente
    pipeline_tiquipaya.calcular_sha256 (misma lógica, una sola
    responsabilidad por módulo) para que correcciones_tiquipaya.py no
    dependa de pipeline_tiquipaya.py (evita import circular: pipeline
    importa este módulo, no al revés)."""
    hasher = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            hasher.update(bloque)
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Validación de schema
# ---------------------------------------------------------------------------

def validar_schema_correccion(correccion):
    """Valida la forma completa de `correccion` contra el schema de
    HANDOFF_CODE_V2.md §16.3. Nunca decide si la corrección es "correcta"
    contablemente (eso es responsabilidad exclusiva del auditor humano):
    solo verifica que el objeto esté bien formado, que el campo a corregir
    sea uno de los autorizados para esa categoría, y que `version_correccion`
    no haya sido alterado tras calcularse.

    Devuelve el version_correccion recalculado (== correccion["version_correccion"]
    si todo es válido). Lanza ValueError("CODIGO:detalle") en cualquier otro
    caso; nunca aplica nada."""
    if not isinstance(correccion, dict):
        raise ValueError("CORRECCION_SCHEMA_INVALIDO:la correccion debe ser un objeto JSON")

    faltantes = [c for c in _CAMPOS_OBLIGATORIOS if c not in correccion]
    if faltantes:
        raise ValueError(f"CORRECCION_SCHEMA_INVALIDO:campos faltantes: {faltantes}")

    categoria = correccion["categoria"]
    if categoria not in CAMPOS_CORREGIBLES:
        raise ValueError(
            f"CORRECCION_SCHEMA_INVALIDO:categoria desconocida: {categoria!r} "
            f"(esperado uno de {sorted(CAMPOS_CORREGIBLES)})"
        )

    campo = correccion["campo_corregido"]
    if campo not in CAMPOS_CORREGIBLES[categoria]:
        raise ValueError(
            f"CORRECCION_CAMPO_NO_CORREGIBLE:{categoria}.{campo} no es corregible "
            f"(permitidos: {sorted(CAMPOS_CORREGIBLES[categoria])})"
        )

    if not isinstance(correccion.get("identificadores"), dict):
        raise ValueError("CORRECCION_SCHEMA_INVALIDO:identificadores debe ser un objeto")

    if not correccion.get("valor_autorizado"):
        raise ValueError("CORRECCION_SCHEMA_INVALIDO:valor_autorizado vacio")

    if not correccion.get("tipo"):
        raise ValueError("CORRECCION_SCHEMA_INVALIDO:tipo vacio")

    if not correccion.get("usuario_auditor"):
        raise ValueError("CORRECCION_SCHEMA_INVALIDO:usuario_auditor vacio")

    if not correccion.get("sha256_origen"):
        raise ValueError("CORRECCION_SCHEMA_INVALIDO:sha256_origen vacio")

    version_calculada = calcular_version_correccion(correccion)
    if correccion["version_correccion"] != version_calculada:
        raise ValueError(
            "CORRECCION_VERSION_INCONSISTENTE:version_correccion no coincide con el "
            "hash determinístico de (categoria,tipo,identificadores,campo_corregido,"
            f"valor_autorizado); esperado {version_calculada}, recibido "
            f"{correccion['version_correccion']!r}"
        )

    return version_calculada


def validar_sha256_origen(ruta_cierre, sha256_origen):
    """CORRECCION_HUERFANA si el .xlsm actual en `ruta_cierre` ya no
    coincide con el sha256_origen que la corrección declara: el cierre
    cambió desde que se generó la corrección y esta ya no aplica sobre
    nada válido. Devuelve el sha256 actual si coincide."""
    actual = calcular_sha256_archivo(ruta_cierre)
    if actual != sha256_origen:
        raise ValueError(
            f"CORRECCION_HUERFANA:sha256_origen ({sha256_origen}) no coincide con el "
            f".xlsm actual en {ruta_cierre} ({actual}); el cierre cambió desde que se "
            "generó esta corrección"
        )
    return actual


def _verificar_valor_original(valor_actual, correccion):
    """Si la corrección declara `valor_original`, debe coincidir con el
    valor realmente presente ahora mismo en el cierre: evita aplicar una
    corrección que el auditor decidió sobre una versión ya desactualizada
    de la excepción (mismo principio que el guardarraíl SHA256_GLOBAL de
    CONTROL 1). `valor_original=None`/ausente no exige nada (la excepción
    original ya venía sin ese dato, p. ej. CI_ASIGNACION_FALTANTE)."""
    esperado = correccion.get("valor_original")
    if esperado is not None and valor_actual != esperado:
        raise ValueError(
            "CORRECCION_VALOR_ORIGINAL_DESACTUALIZADO:el valor actual "
            f"({valor_actual!r}) no coincide con valor_original declarado en la "
            f"corrección ({esperado!r})"
        )


# ---------------------------------------------------------------------------
# Localización del registro a corregir (sobre lo ya leído por excel_io.py)
# ---------------------------------------------------------------------------

def _localizar_ci(cierre, identificadores):
    sfc = identificadores.get("sfc")
    factura = identificadores.get("factura")
    if not sfc or not factura:
        raise ValueError(
            "CORRECCION_IDENTIFICADORES_INVALIDOS:COMUNICACION_INTERNA requiere "
            "identificadores.sfc e identificadores.factura"
        )
    coincidencias = [
        ci for ci in cierre["comunicaciones_internas"]
        if ci.get("sfc") == sfc and ci.get("referencia") == factura
    ]
    if not coincidencias:
        raise ValueError(
            f"CORRECCION_REGISTRO_NO_ENCONTRADO:no existe comunicación interna con "
            f"sfc={sfc!r} factura={factura!r}"
        )
    if len(coincidencias) > 1:
        raise ValueError(
            f"CORRECCION_REGISTRO_AMBIGUO:más de una comunicación interna con "
            f"sfc={sfc!r} factura={factura!r}"
        )
    return coincidencias[0]


def _localizar_voucher(cierre, identificadores):
    sfc = identificadores.get("sfc")
    codigo_informado = identificadores.get("codigo_informado")
    if not sfc or not codigo_informado:
        raise ValueError(
            "CORRECCION_IDENTIFICADORES_INVALIDOS:VOUCHER requiere identificadores.sfc "
            "e identificadores.codigo_informado"
        )
    depositos = cierre["sfc101"]["depositos"] + cierre["sfc102"]["depositos"]
    coincidencias = [
        dep for dep in depositos
        if dep.get("sfc") == sfc and dep.get("asignacion") == codigo_informado
    ]
    if not coincidencias:
        raise ValueError(
            f"CORRECCION_REGISTRO_NO_ENCONTRADO:no existe depósito con sfc={sfc!r} "
            f"codigo_informado={codigo_informado!r}"
        )
    if len(coincidencias) > 1:
        raise ValueError(
            f"CORRECCION_REGISTRO_AMBIGUO:más de un depósito con sfc={sfc!r} "
            f"codigo_informado={codigo_informado!r}"
        )
    return coincidencias[0]


def _localizar_atc(atc_idx, fecha_cierre):
    if atc_idx.get("modo") != "PRECONCILIADO":
        raise ValueError(
            "CORRECCION_ATC_MODO_NO_CORREGIBLE:solo el modo PRECONCILIADO (hoja "
            "'ATC TIQUIPAYA') expone cuenta_contable/asignación corregibles; el modo "
            "LEGADO no trae esas columnas"
        )
    registro = atc_idx["por_fecha"].get(fecha_cierre)
    if registro is None or registro.get("neto") is None or registro.get("comision") is None:
        raise ValueError(
            f"CORRECCION_REGISTRO_NO_ENCONTRADO:no existe fila ATC completa (NETO+COMISION) "
            f"para fecha={fecha_cierre!r}"
        )
    return registro


def _validar_candidato_voucher(cierre, macros_idx, identificadores, valor_autorizado):
    """VOUCHER es el único caso que exige una validación adicional: el
    valor_autorizado NUNCA es un código libre inventado por el auditor,
    tiene que ser uno de los `candidatos` que el propio
    motor_tiquipaya.cruzar_vouchers() ya propuso para ESE depósito (MULTIPLE
    o POSIBLE_TYPO). Un NO_ENCONTRADO sin candidatos nunca es corregible por
    esta vía (ver HANDOFF §16.3, tabla de campos corregibles)."""
    vouchers = motor.cruzar_vouchers(cierre, macros_idx)
    coincidencias = [
        v for v in vouchers["detalle"]
        if v.get("sfc") == identificadores.get("sfc")
        and v.get("codigo_informado") == identificadores.get("codigo_informado")
    ]
    if len(coincidencias) != 1:
        raise ValueError(
            "CORRECCION_REGISTRO_AMBIGUO:no se pudo ubicar unívocamente el voucher "
            "para validar sus candidatos"
        )
    candidatos = coincidencias[0].get("candidatos") or []
    codigos_validos = {c["codigo"] for c in candidatos}
    if not codigos_validos:
        raise ValueError(
            "CORRECCION_SIN_CANDIDATOS:este voucher no trae candidatos propuestos por "
            "el motor (código informado libre no es corregible)"
        )
    if valor_autorizado not in codigos_validos:
        raise ValueError(
            f"CORRECCION_CANDIDATO_INVALIDO:{valor_autorizado!r} no es uno de los "
            f"candidatos propuestos por el motor: {sorted(codigos_validos)}"
        )


# ---------------------------------------------------------------------------
# Aplicación EN MEMORIA — nunca toca el .xlsm, nunca muta los dicts recibidos
# ---------------------------------------------------------------------------

def aplicar_correccion_en_memoria(cierre, macros_idx, atc_idx, correccion):
    """Devuelve (cierre_corregido, atc_idx_corregido): copias profundas de
    `cierre`/`atc_idx` con ÚNICAMENTE `campo_corregido` sobrescrito por
    `valor_autorizado` en el registro localizado por `identificadores`.

    Nunca muta `cierre`/`atc_idx` recibidos (ni siquiera si la validación
    falla a mitad de camino: las copias se descartan junto con la
    excepción). `macros_idx` nunca se modifica: solo se usa de lectura para
    validar los candidatos de VOUCHER. Este es el único punto de contacto
    entre una corrección y los datos del cierre — motor_tiquipaya.py no
    sabe que esto existe."""
    categoria = correccion["categoria"]
    campo = correccion["campo_corregido"]
    valor_autorizado = correccion["valor_autorizado"]

    if categoria == CATEGORIA_VOUCHER:
        # Se valida contra el cierre ORIGINAL (sin corregir todavía): son
        # los mismos candidatos que vio el auditor en la pantalla de FASE 2.
        _validar_candidato_voucher(cierre, macros_idx, correccion["identificadores"], valor_autorizado)

    cierre_corregido = deepcopy(cierre)
    atc_idx_corregido = deepcopy(atc_idx)

    if categoria == CATEGORIA_CI:
        registro = _localizar_ci(cierre_corregido, correccion["identificadores"])
        _verificar_valor_original(registro.get(campo), correccion)
        registro[campo] = valor_autorizado

    elif categoria == CATEGORIA_VOUCHER:
        deposito = _localizar_voucher(cierre_corregido, correccion["identificadores"])
        _verificar_valor_original(deposito.get("asignacion"), correccion)
        deposito["asignacion"] = valor_autorizado

    elif categoria == CATEGORIA_ATC:
        registro = _localizar_atc(atc_idx_corregido, correccion["fecha_cierre"])
        sub_registro, campo_interno = _MAPA_CAMPO_ATC[campo]
        _verificar_valor_original(registro[sub_registro].get(campo_interno), correccion)
        registro[sub_registro][campo_interno] = valor_autorizado

    else:  # pragma: no cover — ya descartado por validar_schema_correccion
        raise ValueError(f"CORRECCION_SCHEMA_INVALIDO:categoria desconocida: {categoria!r}")

    return cierre_corregido, atc_idx_corregido

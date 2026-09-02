"""
motor_tiquipaya.py — ETAPAS 1-5 V2 (Caja Tiquipaya CLOUD) + hardening PRE-SAP.

Orquesta, sobre lo ya leído por excel_io.py:
  ETAPA 3 — cruces determinísticos:
    1. VOUCHERS ↔ MACROS BNB (código de asignación + importe exacto)
    2. ATC mensual: NETO + COMISIÓN = ATC BRUTO del cierre
    3. NETO ATC ↔ MACROS BNB (importe exacto + fecha bancaria compatible,
       nunca ANTERIOR a la fecha de cierre)
    4. Validación mínima de CI (cuenta, asignación, importe no negativo,
       formato por banco, ALQUILERES separado por SFC)
  ETAPA 4 (ejecutar_v2) — universo, ALQUILERES, componentes, recaudación
    explicada y cuadre, con estado estructurado (OK / DIFERENCIA /
    BLOQUEADO_EXCEPCION / USD_CUENTA_PENDIENTE / INDETERMINADO / ERROR).
  ETAPA 5 (construir_asiento) — construcción determinística del asiento
    CARGO/HABER a partir del resultado de ejecutar_v2().

Estas ETAPAS 1-5 ya existen y están validadas contra la regresión sintética
19-08-2026; este archivo está actualmente en hardening PRE-SAP (corrección
de hallazgos de auditoría), no en desarrollo de generación SAP (ETAPA 6).

NO genera SAP, NO mueve cierres, NO marca procesado, NO genera reportes.
Claude no procesa filas: todo el recorrido de filas ocurre aquí, en Python,
con Decimal.

Uso:
    python motor_tiquipaya.py <cierre.xlsm> <macros.xlsm> <atc.xlsx>
"""

import sys
import json
from decimal import Decimal, InvalidOperation

import excel_io as io


# ---------------------------------------------------------------------------
# Bancos con formato de asignación conocido
# ---------------------------------------------------------------------------

_BANCOS_ALFANUMERICOS = {"BNB", "BMSC"}
_BANCOS_NUMERICOS = {
    "BCP", "BISA", "BANCO UNION", "BUSA", "BANECO", "BANCO ECONOMICO",
}


def _es_numerico(texto):
    compacto = texto.replace(" ", "").replace("-", "")
    return compacto.isdigit() and len(compacto) > 0


def _tiene_letra(texto):
    return any(ch.isalpha() for ch in texto)


# ---------------------------------------------------------------------------
# 1. VOUCHERS ↔ MACROS BNB
# ---------------------------------------------------------------------------

_VARIANTES_MAX = 4096  # límite defensivo de combinaciones 0/O


def _variantes_0_o(codigo_norm):
    """Genera variantes de codigo_norm intercambiando únicamente '0' <-> 'O'
    en cada posición donde aparezca alguno de esos dos caracteres."""
    posiciones = [i for i, ch in enumerate(codigo_norm) if ch in ("0", "O")]
    if not posiciones or len(posiciones) > 12:
        return []
    variantes = set()
    total_combos = 1 << len(posiciones)
    if total_combos > _VARIANTES_MAX:
        return []
    chars = list(codigo_norm)
    for mask in range(total_combos):
        nuevo = chars[:]
        for k, pos in enumerate(posiciones):
            if (mask >> k) & 1:
                nuevo[pos] = "O" if chars[pos] == "0" else "0"
        variante = "".join(nuevo)
        if variante != codigo_norm:
            variantes.add(variante)
    return list(variantes)


def _hamming_o_none(a, b):
    if len(a) != len(b):
        return None
    return sum(1 for x, y in zip(a, b) if x != y)


def _clasificar_voucher(codigo_informado, importe_str, macros_idx):
    codigo_norm = io.normalize_codigo(codigo_informado)
    por_codigo = macros_idx["por_codigo"]
    por_importe = macros_idx["por_importe"]

    # 1) MATCH_EXACTO: código + importe exactos, candidato único
    directos = [m for m in por_codigo.get(codigo_norm, []) if m["importe"] == importe_str]
    if len(directos) == 1:
        m = directos[0]
        return {
            "estado": "MATCH_EXACTO",
            "codigo_informado": codigo_informado,
            "codigo_encontrado": m["codigo"],
            "importe": importe_str,
            "fecha_bancaria": m["fecha"],
        }
    if len(directos) > 1:
        return {
            "estado": "MULTIPLE",
            "codigo_informado": codigo_informado,
            "importe": importe_str,
            "candidatos": len(directos),
        }

    # 2) AUTOCORRECCION_0_O: únicamente dígito 0 <-> letra O, importe exacto,
    #    candidato único e inequívoco.
    encontrados_0o = []
    for variante in _variantes_0_o(codigo_norm):
        for m in por_codigo.get(variante, []):
            if m["importe"] == importe_str:
                encontrados_0o.append(m)
    if len(encontrados_0o) == 1:
        m = encontrados_0o[0]
        return {
            "estado": "AUTOCORRECCION_0_O",
            "codigo_informado": codigo_informado,
            "codigo_encontrado": m["codigo"],
            "importe": importe_str,
            "fecha_bancaria": m["fecha"],
        }
    if len(encontrados_0o) > 1:
        return {
            "estado": "MULTIPLE",
            "codigo_informado": codigo_informado,
            "importe": importe_str,
            "candidatos": len(encontrados_0o),
        }

    # 3) POSIBLE_TYPO: mismo importe, código distinto por 1-2 caracteres
    #    (cambios que no son únicamente 0<->O). No se resuelve automáticamente.
    candidatos_importe = por_importe.get(importe_str, [])
    typos = []
    for m in candidatos_importe:
        otro_norm = io.normalize_codigo(m["codigo"])
        if otro_norm == codigo_norm:
            continue
        dist = _hamming_o_none(codigo_norm, otro_norm)
        if dist is not None and 0 < dist <= 2:
            typos.append(m)
    if typos:
        return {
            "estado": "POSIBLE_TYPO",
            "codigo_informado": codigo_informado,
            "importe": importe_str,
            "candidatos": [{"codigo": m["codigo"], "fecha": m["fecha"]} for m in typos],
        }

    # 4) NO_ENCONTRADO
    return {
        "estado": "NO_ENCONTRADO",
        "codigo_informado": codigo_informado,
        "importe": importe_str,
    }


def cruzar_vouchers(cierre, macros_idx):
    depositos = cierre["sfc101"]["depositos"] + cierre["sfc102"]["depositos"]
    resultados = []
    for dep in depositos:
        r = _clasificar_voucher(dep["asignacion"], dep["importe"], macros_idx)
        r["sfc"] = dep["sfc"]
        # Fecha propia del depósito (columna FECHA DE DEPOSITO del
        # cierre), no la fecha bancaria de MACROS: es la fuente única de
        # fecha_valor/texto_posicion del VOUCHER (ver construir_asiento).
        r["fecha_deposito"] = dep.get("fecha_deposito")
        resultados.append(r)

    conteo = {"MATCH_EXACTO": 0, "AUTOCORRECCION_0_O": 0, "NO_ENCONTRADO": 0,
              "MULTIPLE": 0, "POSIBLE_TYPO": 0}
    importe_total = Decimal("0")
    for r in resultados:
        conteo[r["estado"]] += 1
        importe_total += Decimal(r["importe"])

    return {
        "cantidad": len(resultados),
        "importe": io.money_str(importe_total),
        "conteo": conteo,
        "detalle": resultados,
    }


# ---------------------------------------------------------------------------
# 2 y 3. ATC mensual: NETO + COMISION = BRUTO, y NETO ↔ MACROS BNB
# ---------------------------------------------------------------------------

def cruzar_atc(cierre, atc_idx, macros_idx):
    fecha_cierre = cierre["fecha_cierre"]
    bruto_cierre = Decimal(cierre["sfc101"]["cobros_atc"]) + Decimal(cierre["sfc102"]["cobros_atc"])
    bruto_str = io.money_str(bruto_cierre)

    if bruto_cierre == 0:
        # ATC BRUTO = 0.00: el día no tuvo cobros con tarjeta. ATC está
        # INACTIVO/NO APLICA para este cierre: no se exige fila en el ATC
        # mensual, no se busca NETO en MACROS y esto NUNCA es una
        # excepción (no cuenta para excepciones_bloqueantes). El cierre
        # sigue su curso normal sin componente ATC.
        return {
            "bruto": bruto_str,
            "neto": "0.00",
            "comision": "0.00",
            "diferencia": "0.00",
            "estado_validacion": "ATC_NO_APLICA",
            "estado_match_macros": None,
            "codigo_encontrado": None,
            "fecha_bancaria_encontrada": None,
            "excepcion": False,
        }

    registro = atc_idx.get(fecha_cierre)
    if registro is None or registro["neto"] is None or registro["comision"] is None:
        return {
            "bruto": bruto_str,
            "neto": None,
            "comision": None,
            "diferencia": None,
            "estado_validacion": "ATC_FECHA_NO_ENCONTRADA",
            "estado_match_macros": None,
            "codigo_encontrado": None,
            "fecha_bancaria_encontrada": None,
            "excepcion": True,
        }

    neto = Decimal(registro["neto"])
    comision = Decimal(registro["comision"])
    suma = neto + comision
    diferencia = suma - bruto_cierre
    valida = diferencia == 0

    resultado = {
        "bruto": bruto_str,
        "neto": io.money_str(neto),
        "comision": io.money_str(comision),
        "diferencia": io.money_str(diferencia),
        "estado_validacion": "OK" if valida else "ATC_DIFERENCIA",
        "estado_match_macros": None,
        "codigo_encontrado": None,
        "fecha_bancaria_encontrada": None,
        "excepcion": not valida,
    }

    if not valida:
        return resultado

    # Buscar NETO en MACROS BNB por importe exacto + fecha bancaria
    # compatible: nunca ANTERIOR a la fecha de cierre. Fechas posteriores
    # sí son válidas. No se inventa un máximo arbitrario de días de
    # tolerancia. Un movimiento sin fecha no se puede evaluar y se excluye.
    candidatos = macros_idx["por_importe"].get(io.money_str(neto), [])
    candidatos_compatibles = [
        m for m in candidatos if m.get("fecha") and m["fecha"] >= fecha_cierre
    ]
    if len(candidatos_compatibles) == 1:
        m = candidatos_compatibles[0]
        resultado["estado_match_macros"] = "ATC_MATCH_EXACTO"
        resultado["codigo_encontrado"] = m["codigo"]
        resultado["fecha_bancaria_encontrada"] = m["fecha"]
    elif len(candidatos_compatibles) == 0:
        resultado["estado_match_macros"] = "ATC_SIN_CANDIDATO"
        resultado["excepcion"] = True
    else:
        resultado["estado_match_macros"] = "ATC_MULTIPLE"
        resultado["excepcion"] = True

    return resultado


# ---------------------------------------------------------------------------
# 2b y 3b. ATC PRECONCILIADO (ETAPA 6 — maestro único, hoja "ATC TIQUIPAYA")
# ---------------------------------------------------------------------------
#
# A diferencia de cruzar_atc() (arriba), aquí el ATC YA VIENE CONCILIADO:
# NUNCA se cruza contra MACROS (no se recibe macros_idx, no se buscan
# candidatos, no se busca el NETO por importe, no se aplica ventana de
# fechas bancarias). Cuenta contable, detalle, monto y asignación del
# NETO y de la COMISIÓN se toman literalmente de "ATC TIQUIPAYA" para la
# fecha del cierre. Único control: NETO + COMISIÓN debe reconstruir el
# ATC BRUTO del cierre (Decimal, 2 decimales); si no coincide, o si
# faltan las líneas necesarias, es blocker. cruzar_atc() (legado, ATC
# mensual separado + cruce contra MACROS) no se toca ni se usa aquí.

_ATC_ASIGNACION_REVISAR = "REVISAR"


def cruzar_atc_preconciliado(cierre, atc_preconciliado_por_fecha):
    """Si una asignación (NETO o COMISION) llega como "REVISAR" se
    conserva literal, NUNCA es blocker y se registra como advertencia
    "ATC_ASIGNACION_REVISAR" (no bloqueante, no se busca ni se inventa
    un código alternativo)."""
    fecha_cierre = cierre["fecha_cierre"]
    bruto_cierre = Decimal(cierre["sfc101"]["cobros_atc"]) + Decimal(cierre["sfc102"]["cobros_atc"])
    bruto_str = io.money_str(bruto_cierre)

    base = {
        "modo": "PRECONCILIADO",
        "bruto": bruto_str,
        "neto_cuenta_contable": None, "neto_detalle": None, "neto_asignacion": None,
        "comision_cuenta_contable": None, "comision_detalle": None, "comision_asignacion": None,
        "advertencias": [],
    }

    if bruto_cierre == 0:
        # Misma regla que cruzar_atc(): día sin cobros con tarjeta, ATC
        # inactivo/no aplica. Nunca es excepción, no exige filas en
        # "ATC TIQUIPAYA".
        return {
            **base,
            "neto": "0.00", "comision": "0.00", "diferencia": "0.00",
            "estado_validacion": "ATC_NO_APLICA",
            "excepcion": False,
        }

    registro = atc_preconciliado_por_fecha.get(fecha_cierre)
    if registro is None or registro.get("neto") is None or registro.get("comision") is None:
        # Faltan las líneas necesarias para reconstruir el bruto.
        return {
            **base,
            "neto": None, "comision": None, "diferencia": None,
            "estado_validacion": "ATC_FECHA_NO_ENCONTRADA",
            "excepcion": True,
        }

    neto_row = registro["neto"]
    comision_row = registro["comision"]
    neto = Decimal(neto_row["monto"])
    comision = Decimal(comision_row["monto"])
    suma = neto + comision
    diferencia = suma - bruto_cierre
    valida = diferencia == 0

    advertencias = []
    if _ATC_ASIGNACION_REVISAR in (neto_row.get("asignacion"), comision_row.get("asignacion")):
        advertencias.append("ATC_ASIGNACION_REVISAR")

    return {
        **base,
        "neto": io.money_str(neto),
        "comision": io.money_str(comision),
        "diferencia": io.money_str(diferencia),
        "estado_validacion": "OK" if valida else "ATC_DIFERENCIA",
        "excepcion": not valida,
        "neto_cuenta_contable": neto_row.get("cuenta_contable"),
        "neto_detalle": neto_row.get("detalle"),
        "neto_asignacion": neto_row.get("asignacion"),
        "comision_cuenta_contable": comision_row.get("cuenta_contable"),
        "comision_detalle": comision_row.get("detalle"),
        "comision_asignacion": comision_row.get("asignacion"),
        "advertencias": advertencias,
    }


# ---------------------------------------------------------------------------
# 4. Validación mínima de Comunicaciones Internas
# ---------------------------------------------------------------------------

def validar_ci(cierre):
    validas = 0
    detalle_validas = []
    bloqueantes = []
    advertencias = []
    alquileres = []
    alquileres_por_sfc = {"SFC101": Decimal("0"), "SFC102": Decimal("0")}

    for ci in cierre["comunicaciones_internas"]:
        if ci["alquileres"]:
            alquileres.append(ci)
            sfc = ci["sfc"]
            alquileres_por_sfc[sfc] = alquileres_por_sfc.get(sfc, Decimal("0")) + Decimal(ci["importe"])
            continue  # EXCLUIDO_ALQUILERES: sin validación de cuenta/banco/formato

        problema_bloqueante = None
        if not ci["cuenta_contable"]:
            problema_bloqueante = "CI_CUENTA_FALTANTE"
        elif not ci["asignacion"]:
            problema_bloqueante = "CI_ASIGNACION_FALTANTE"
        elif Decimal(ci["importe"]) < 0:
            problema_bloqueante = "CI_IMPORTE_NEGATIVO"

        if problema_bloqueante:
            bloqueantes.append({
                "sfc": ci["sfc"], "referencia": ci["referencia"],
                "importe": ci["importe"], "tipo": problema_bloqueante,
            })
            continue

        banco_norm = io.normalize_text(ci["banco"]) if ci["banco"] else ""
        asignacion = ci["asignacion"].strip()
        formato_ok = True
        if banco_norm in _BANCOS_ALFANUMERICOS:
            formato_ok = _tiene_letra(asignacion)
        elif banco_norm in _BANCOS_NUMERICOS:
            formato_ok = _es_numerico(asignacion)
        # banco no reconocido: no se valida formato (sin regla definida)

        if not formato_ok:
            advertencias.append({
                "sfc": ci["sfc"], "referencia": ci["referencia"],
                "banco": ci["banco"], "asignacion": asignacion,
            })

        validas += 1
        detalle_validas.append({
            "sfc": ci["sfc"],
            "referencia": ci["referencia"],
            "importe": ci["importe"],
            "cuenta_contable": ci["cuenta_contable"],
            "asignacion": asignacion,
            # Glosa literal de "GLOSA ASIENTO COMUNICACIONES INTERNAS",
            # None si la hoja no la trae. Única fuente de texto_posicion
            # para la partida CI (nunca se reconstruye desde referencia
            # ni ninguna otra columna, ver construir_asiento).
            "glosa": ci.get("glosa"),
            # Fecha propia de la CI (columna FECHA2), None si la hoja no
            # la trae. Nunca se sustituye por la fecha del cierre.
            "fecha_ci": ci.get("fecha_ci"),
        })

    importe_alquileres = sum((Decimal(ci["importe"]) for ci in alquileres), Decimal("0"))

    return {
        "cantidad": len(cierre["comunicaciones_internas"]),
        "importe": io.money_str(sum((Decimal(ci["importe"]) for ci in cierre["comunicaciones_internas"]), Decimal("0"))),
        "validas": validas,
        "detalle_validas": detalle_validas,
        "bloqueantes": bloqueantes,
        "advertencias": advertencias,
        "alquileres_cantidad": len(alquileres),
        "alquileres_importe": io.money_str(importe_alquileres),
        # ALQUILERES separado por SFC: se excluye del asiento pero se
        # conserva el importe por SFC para ajustar el HABER (ver
        # _detalle_para_asiento y construir_asiento).
        "alquileres_por_sfc": {k: io.money_str(v) for k, v in alquileres_por_sfc.items()},
    }


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def _cruzar_sobre_cierre(cierre, macros_idx, atc_idx):
    """Aplica los cruces de ETAPA 3 sobre un `cierre` ya leído en memoria.

    No abre ningún archivo: recibe `cierre`, `macros_idx` y `atc_idx` ya
    cargados por el llamador. Factoriza la lógica compartida entre
    ejecutar_cruces() (ETAPA 3 standalone) y ejecutar_v2() (ETAPA 4, que
    necesita los mismos cruces pero sin volver a abrir el CIERRE).

    `atc_idx` es siempre el resultado de io.leer_atc_mensual():
    {"modo": "LEGADO"|"PRECONCILIADO", "por_fecha": {...}}. Según el modo
    (decidido por io.leer_atc_mensual() según el NOMBRE de hoja
    encontrado, nunca por un flag explícito) se despacha a cruzar_atc()
    (legado, cruza contra MACROS) o a cruzar_atc_preconciliado() (ATC ya
    conciliado, nunca cruza contra MACROS).
    """
    vouchers = cruzar_vouchers(cierre, macros_idx)

    datos_atc = atc_idx["por_fecha"]
    if atc_idx.get("modo") == "PRECONCILIADO":
        atc = cruzar_atc_preconciliado(cierre, datos_atc)
    else:
        atc = cruzar_atc(cierre, datos_atc, macros_idx)

    ci = validar_ci(cierre)

    excepciones_bloqueantes = (
        vouchers["conteo"]["NO_ENCONTRADO"]
        + vouchers["conteo"]["MULTIPLE"]
        + vouchers["conteo"]["POSIBLE_TYPO"]
        + (1 if atc["excepcion"] else 0)
        + len(ci["bloqueantes"])
    )

    resultado = "CRUCES V2 OK" if excepciones_bloqueantes == 0 else "CRUCES V2 ERROR"

    return {
        "fecha_cierre": cierre["fecha_cierre"],
        "vouchers": vouchers,
        "atc": atc,
        "ci": ci,
        "excepciones_bloqueantes_total": excepciones_bloqueantes,
        "resultado": resultado,
    }


def ejecutar_cruces(ruta_cierre, ruta_macros, ruta_atc):
    """ETAPA 3 standalone: abre los tres archivos y devuelve los cruces."""
    cierre = io.leer_cierre(ruta_cierre)
    macros_idx = io.leer_macros_bnb(ruta_macros)   # UNA sola apertura
    atc_idx = io.leer_atc_mensual(ruta_atc)         # UNA sola apertura
    return _cruzar_sobre_cierre(cierre, macros_idx, atc_idx)


# ---------------------------------------------------------------------------
# ETAPA 4: universo, ALQUILERES, componentes, recaudación explicada, cuadre
# ---------------------------------------------------------------------------
#
# Consume exclusivamente las estructuras ya calculadas por leer_cierre() y
# los cruces de ETAPA 3 (cruzar_vouchers/cruzar_atc/validar_ci). No vuelve a
# analizar Excel manualmente, no construye asiento, no genera SAP, no
# actualiza controles, no mueve cierres y no genera informes.

_ESTADOS_VOUCHER_VALIDOS = ("MATCH_EXACTO", "AUTOCORRECCION_0_O")


def calcular_universo(cierre):
    """UNIVERSO_ORIGINAL = TOTAL_MOVIMIENTO SFC101 + TOTAL_MOVIMIENTO SFC102."""
    sfc101 = Decimal(cierre["sfc101"]["total_movimiento"])
    sfc102 = Decimal(cierre["sfc102"]["total_movimiento"])
    return io.money_str(sfc101 + sfc102)


def calcular_componentes(cierre, cruces):
    """
    VOUCHERS_VALIDOS = suma de vouchers ya resueltos (MATCH_EXACTO o
        AUTOCORRECCION_0_O); vouchers en excepción no se suman.
    CI_OPERATIVAS = suma de detalle_validas de validar_ci: CI realmente
        válidas y operativas (excluye ALQUILERES y excluye cualquier CI
        bloqueante -cuenta/asignación faltante, importe negativo-, que no
        puede explicar recaudación contabilizable aunque el cierre termine
        bloqueado por otra excepción).
    ATC_BRUTO = ATC SFC101 + ATC SFC102 (ya calculado por cruzar_atc).
    DOLARES = DOLARES SFC101 + DOLARES SFC102 si > 0; si no, "0.00" (no
        activo, no se trata como faltante).
    """
    vouchers_validos = sum(
        (
            Decimal(v["importe"])
            for v in cruces["vouchers"]["detalle"]
            if v["estado"] in _ESTADOS_VOUCHER_VALIDOS
        ),
        Decimal("0"),
    )

    ci_operativas = sum(
        (Decimal(ci["importe"]) for ci in cruces["ci"]["detalle_validas"]),
        Decimal("0"),
    )

    atc_bruto = Decimal(cruces["atc"]["bruto"])

    dolares = Decimal(cierre["sfc101"]["dolares"]) + Decimal(cierre["sfc102"]["dolares"])
    dolares_activo = dolares if dolares > 0 else Decimal("0")

    return {
        "vouchers": io.money_str(vouchers_validos),
        "ci_operativas": io.money_str(ci_operativas),
        "atc_bruto": io.money_str(atc_bruto),
        "dolares": io.money_str(dolares_activo),
    }


def _ejecutar_v2_sobre_cierre(cierre, macros_idx, atc_idx):
    """Aplica ETAPA 3 (cruces) + ETAPA 4 (universo, ALQUILERES,
    componentes, recaudación explicada, cuadre) sobre un `cierre` y unos
    índices `macros_idx`/`atc_idx` YA cargados en memoria. No abre ningún
    archivo ni repite ninguna regla: es exactamente el mismo
    procesamiento que hacía ejecutar_v2() después de leer sus tres
    archivos, factorizado aquí para que ejecutar_lote_v2() pueda
    reutilizar macros_idx/atc_idx entre varios cierres del mismo mes sin
    reabrir MACROS ni ATC por cada uno.

    Devuelve EXACTAMENTE la misma estructura que ejecutar_v2().
    """
    try:
        cruces = _cruzar_sobre_cierre(cierre, macros_idx, atc_idx)

        universo_original = calcular_universo(cierre)
        alquileres = cruces["ci"]["alquileres_importe"]
        universo_ajustado = io.money_str(Decimal(universo_original) - Decimal(alquileres))

        componentes = calcular_componentes(cierre, cruces)

        recaudacion_explicada = io.money_str(
            Decimal(componentes["vouchers"])
            + Decimal(componentes["ci_operativas"])
            + Decimal(componentes["atc_bruto"])
            + Decimal(componentes["dolares"])
        )

        diferencia = io.money_str(Decimal(universo_ajustado) - Decimal(recaudacion_explicada))

        excepciones_bloqueantes = cruces["excepciones_bloqueantes_total"]
        dolares_pendiente = Decimal(componentes["dolares"]) > 0

        if excepciones_bloqueantes > 0:
            estado = "BLOQUEADO_EXCEPCION"
        elif dolares_pendiente:
            estado = "USD_CUENTA_PENDIENTE"
        elif Decimal(diferencia) != 0:
            estado = "DIFERENCIA"
        else:
            estado = "OK"

        detalle = _detalle_para_asiento(cierre, cruces, componentes)
    except (ValueError, KeyError, TypeError, ArithmeticError, InvalidOperation) as exc:
        return {
            "fecha": cierre.get("fecha_cierre"),
            "estado": "ERROR",
            "error": str(exc),
            "etapa": "CRUCES_O_CUADRE",
        }

    return {
        "fecha": cierre["fecha_cierre"],
        "universo_original": universo_original,
        "alquileres": alquileres,
        "universo_ajustado": universo_ajustado,
        "componentes": componentes,
        "recaudacion_explicada": recaudacion_explicada,
        "diferencia": diferencia,
        "excepciones_bloqueantes": excepciones_bloqueantes,
        "estado": estado,
        "detalle": detalle,
    }


def ejecutar_v2(ruta_cierre, ruta_macros, ruta_atc):
    """
    ETAPA 4: orquesta ETAPA 2 (extracción) + ETAPA 3 (cruces) + ETAPA 4
    (universo, ALQUILERES, componentes, recaudación explicada, cuadre)
    en una sola corrida. Cada archivo se abre UNA sola vez.

    Nunca deja escapar una excepción sin respuesta: tanto un fallo de
    extracción como un fallo durante cruces/cuadre/armado del detalle
    devuelven un estado estructurado (INDETERMINADO o ERROR) con motivo,
    en lugar de reventar la corrida o esconder el problema como si el
    cierre estuviera OK.

    Si DOLARES > 0.00 el estado nunca puede ser "OK": se devuelve
    "USD_CUENTA_PENDIENTE" de forma explícita (la cuenta USD no está
    parametrizada), para que un cierre con USD pendiente no pueda
    marcarse después como procesado normal.

    API pública sin cambios: internamente solo abre los tres archivos y
    delega el procesamiento a _ejecutar_v2_sobre_cierre(). Para procesar
    varios cierres del mismo mes reutilizando MACROS/ATC ya cargados, ver
    ejecutar_lote_v2().
    """
    try:
        cierre = io.leer_cierre(ruta_cierre)
        macros_idx = io.leer_macros_bnb(ruta_macros)   # UNA sola apertura
        atc_idx = io.leer_atc_mensual(ruta_atc)         # UNA sola apertura
    except (ValueError, KeyError) as exc:
        return {
            "fecha": None,
            "estado": "INDETERMINADO",
            "error": str(exc),
            "etapa": "EXTRACCION",
        }

    return _ejecutar_v2_sobre_cierre(cierre, macros_idx, atc_idx)


def _detalle_para_asiento(cierre, cruces, componentes):
    """Expone, sin recalcular nada, los datos crudos ya producidos por la
    ETAPA 2 (cierre) y la ETAPA 3 (cruces) que la ETAPA 5 necesita para
    construir el asiento: totales HABER por SFC, vouchers ya confirmados,
    CI ya validadas y ATC ya cruzado contra MACROS.

    ALQUILERES se excluye del asiento (no se crea partida ALQUILERES ni se
    compensa con otra cuenta), pero su importe se conserva separado por
    SFC para ajustar el HABER: HABER SFCxxx = TOTAL SFCxxx - ALQUILERES de
    ese SFC. El total HABER resultante coincide con el UNIVERSO_AJUSTADO.
    """
    alquileres_por_sfc = cruces["ci"]["alquileres_por_sfc"]
    sfc101_total = cierre["sfc101"]["total_movimiento"]
    sfc102_total = cierre["sfc102"]["total_movimiento"]
    sfc101_haber = io.money_str(
        Decimal(sfc101_total) - Decimal(alquileres_por_sfc.get("SFC101", "0.00"))
    )
    sfc102_haber = io.money_str(
        Decimal(sfc102_total) - Decimal(alquileres_por_sfc.get("SFC102", "0.00"))
    )

    vouchers_confirmados = [
        {
            "sfc": v["sfc"],
            "importe": v["importe"],
            "codigo_confirmado": v["codigo_encontrado"],
            "codigo_informado": v["codigo_informado"],
            "fecha_bancaria": v.get("fecha_bancaria"),
            # Fecha propia del depósito (FECHA DE DEPOSITO del cierre):
            # fuente única de fecha_valor/texto_posicion del VOUCHER en
            # construir_asiento (nunca la fecha bancaria de MACROS).
            "fecha_deposito": v.get("fecha_deposito"),
            "estado": v["estado"],
        }
        for v in cruces["vouchers"]["detalle"]
        if v["estado"] in _ESTADOS_VOUCHER_VALIDOS
    ]

    atc = cruces["atc"]
    # ATC_NO_APLICA (bruto=0.00) nunca es excepción, pero tampoco genera
    # atc_neto/atc_comision: es una ausencia legítima de componente ATC,
    # distinta de un ATC que sí aplica y no pudo determinarse. atc_aplica
    # es lo que permite a construir_asiento() distinguir ambos casos.
    atc_aplica = Decimal(atc["bruto"]) > 0
    atc_advertencias = []

    if not atc_aplica:
        atc_neto = None
        atc_comision = None
    elif atc.get("modo") == "PRECONCILIADO":
        # ATC ya conciliado (hoja "ATC TIQUIPAYA"): cuenta, detalle y
        # asignación se toman literalmente de cruzar_atc_preconciliado(),
        # sin cruzar contra MACROS. Sin fuente real de fecha bancaria en
        # este formato: fecha_bancaria siempre None (ver sección D,
        # nunca se usa la fecha de cierre como reemplazo).
        atc_advertencias = atc.get("advertencias", [])
        if not atc["excepcion"] and atc["estado_validacion"] == "OK":
            atc_neto = {
                "importe": atc["neto"],
                "codigo_confirmado": atc["neto_asignacion"],
                "fecha_bancaria": None,
                "cuenta_contable": atc["neto_cuenta_contable"],
                "texto_detalle": atc["neto_detalle"],
            }
            atc_comision = {
                "importe": atc["comision"],
                "asignacion": atc["comision_asignacion"],
                "cuenta_contable": atc["comision_cuenta_contable"],
                "texto_detalle": atc["comision_detalle"],
            }
        else:
            atc_neto = None
            atc_comision = None
    else:
        # LEGADO: comportamiento histórico, sin cambios.
        if not atc["excepcion"] and atc["estado_match_macros"] == "ATC_MATCH_EXACTO":
            atc_neto = {
                "importe": atc["neto"],
                "codigo_confirmado": atc["codigo_encontrado"],
                "fecha_bancaria": atc["fecha_bancaria_encontrada"],
            }
            atc_comision = {"importe": atc["comision"]}
        else:
            atc_neto = None
            atc_comision = None

    return {
        "sfc101_total": sfc101_total,
        "sfc102_total": sfc102_total,
        "sfc101_haber": sfc101_haber,
        "sfc102_haber": sfc102_haber,
        "alquileres_sfc101": alquileres_por_sfc.get("SFC101", "0.00"),
        "alquileres_sfc102": alquileres_por_sfc.get("SFC102", "0.00"),
        "vouchers_confirmados": vouchers_confirmados,
        "ci_validas": cruces["ci"]["detalle_validas"],
        "atc_neto": atc_neto,
        "atc_comision": atc_comision,
        "atc_aplica": atc_aplica,
        "atc_estado": atc["estado_validacion"],
        "atc_advertencias": atc_advertencias,
        "dolares": componentes["dolares"],
    }


# ---------------------------------------------------------------------------
# ETAPA 5: construcción determinística del asiento
# ---------------------------------------------------------------------------
#
# Consume exclusivamente el resultado ya producido por ejecutar_v2() (sus
# claves de nivel superior más "detalle", ETAPA 4/5). No reabre archivos, no
# repite extracción ni cruces, no genera SAP. Solo arma partidas CARGO/HABER
# cuando el cierre está OK, sin excepciones bloqueantes y con diferencia
# 0.00. Nunca crea partidas artificiales para forzar el cuadre.

_SOCIEDAD = "BO01"
_CENTRO_BENEFICIO = "10010101"
_CUENTA_HABER = "110101001"
_CUENTA_VOUCHER_ATC = "110103012"
_CUENTA_ATC_COMISION = "110201008"

# ETAPA 8: texto_posicion (SGTXT) autorizado para las 2 líneas HABER
# normales (UNIVERSO_SFC101/UNIVERSO_SFC102). Literal, no se reconstruye
# a partir de ningún otro dato del cierre.
_TEXTO_HABER_SFC101 = "RECAUDACION CAJA SFC101"
_TEXTO_HABER_SFC102 = "RECAUDACION CAJA SFC102"

_MESES_ABREV = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DIC",
}


def _asignacion_comision(fecha_iso):
    """'TIQUIPAYA <MES>' a partir de la fecha de cierre YYYY-MM-DD.
    Nunca supera 18 caracteres (p. ej. 'TIQUIPAYA AGO' = 13)."""
    if not fecha_iso:
        return None
    _, mes, _ = fecha_iso.split("-")
    abrev = _MESES_ABREV.get(int(mes), "")
    return f"TIQUIPAYA {abrev}"[:18]


def _texto_voucher(fecha_deposito_iso):
    """'DEPOSITO BNB DD/MM/YYYY' a partir de la fecha propia del depósito
    (YYYY-MM-DD). None si el depósito no trae esa fecha (nunca se
    inventa ni se sustituye por otra)."""
    if not fecha_deposito_iso:
        return None
    anio, mes, dia = fecha_deposito_iso.split("-")
    return f"DEPOSITO BNB {dia}/{mes}/{anio}"


def _partida(cuenta_mayor, cargo, haber, asignacion, origen, sfc_origen,
             texto_posicion=None, fecha_valor=None, codigo_informado_original=None):
    return {
        "sociedad": _SOCIEDAD,
        "cuenta_mayor": cuenta_mayor,
        "texto_posicion": texto_posicion,
        "cargo": io.money_str(cargo),
        "haber": io.money_str(haber),
        "centro_beneficio": _CENTRO_BENEFICIO,
        "fecha_valor": fecha_valor,
        "asignacion": asignacion,
        "origen": origen,
        "sfc_origen": sfc_origen,
        "codigo_informado_original": codigo_informado_original,
    }


def _validar_partidas(partidas, total_cargo, total_haber, diferencia):
    """Verifica, sin forzar nada, que el asiento ya construido cumpla las
    reglas obligatorias de ETAPA 5. Devuelve la lista de problemas
    encontrados (vacía si el asiento es válido)."""
    problemas = []

    if total_cargo != total_haber:
        problemas.append("TOTAL_CARGO_DISTINTO_DE_TOTAL_HABER")
    if diferencia != 0:
        problemas.append("DIFERENCIA_DISTINTA_DE_CERO")

    haber_normales = [p for p in partidas if p["origen"] in ("UNIVERSO_SFC101", "UNIVERSO_SFC102")]
    if len(haber_normales) != 2:
        problemas.append("CANTIDAD_HABER_NORMAL_INVALIDA")

    for p in partidas:
        cargo_dec = Decimal(p["cargo"])
        haber_dec = Decimal(p["haber"])

        if p["origen"] == "ALQUILERES":
            problemas.append("ALQUILERES_PRESENTE_EN_ASIENTO")
        if cargo_dec < 0 or haber_dec < 0:
            problemas.append(f"IMPORTE_NEGATIVO:{p['origen']}")
        if cargo_dec > 0 and haber_dec > 0:
            problemas.append(f"CARGO_Y_HABER_SIMULTANEO:{p['origen']}")

        if p["origen"] in ("UNIVERSO_SFC101", "UNIVERSO_SFC102") and p["cuenta_mayor"] != _CUENTA_HABER:
            problemas.append(f"HABER_CUENTA_INVALIDA:{p['origen']}")
        if p["origen"] == "VOUCHER" and p["cuenta_mayor"] != _CUENTA_VOUCHER_ATC:
            problemas.append("VOUCHER_CUENTA_INVALIDA")
        if p["origen"] == "CI" and (not p["cuenta_mayor"] or not p["asignacion"]):
            problemas.append("CI_SIN_CUENTA_O_ASIGNACION")
        if p["origen"] == "ATC_NETO" and p["cuenta_mayor"] != _CUENTA_VOUCHER_ATC:
            problemas.append("ATC_NETO_CUENTA_INVALIDA")
        if p["origen"] == "ATC_COMISION" and p["cuenta_mayor"] != _CUENTA_ATC_COMISION:
            problemas.append("ATC_COMISION_CUENTA_INVALIDA")

    return problemas


def construir_asiento(resultado_v2):
    """ETAPA 5: construye el asiento contable determinístico a partir del
    resultado ya calculado por ejecutar_v2() (incluida su clave "detalle").

    Solo construye partidas cuando el cierre está en estado "OK", con
    diferencia 0.00 y cero excepciones bloqueantes. Si DOLARES > 0.00 (y la
    cuenta USD no está parametrizada, que es el caso actual), no construye
    el asiento completo y devuelve estado USD_CUENTA_PENDIENTE. En
    cualquier otro caso de precondición no cumplida, devuelve NO_ASIENTO.
    Nunca fuerza el cuadre ni inventa datos.
    """
    fecha_cierre = resultado_v2.get("fecha")

    if resultado_v2.get("estado") == "USD_CUENTA_PENDIENTE":
        return {
            "fecha_cierre": fecha_cierre,
            "estado": "USD_CUENTA_PENDIENTE",
            "motivo": "DOLARES > 0.00 y la cuenta USD no está parametrizada.",
            "partidas": [],
        }

    condiciones_ok = (
        resultado_v2.get("estado") == "OK"
        and resultado_v2.get("excepciones_bloqueantes") == 0
        and "diferencia" in resultado_v2
        and Decimal(resultado_v2["diferencia"]) == 0
        and resultado_v2.get("detalle") is not None
    )
    if not condiciones_ok:
        return {
            "fecha_cierre": fecha_cierre,
            "estado": "NO_ASIENTO",
            "motivo": f"Cierre no habilitado para asiento (estado={resultado_v2.get('estado')}).",
            "partidas": [],
        }

    detalle = resultado_v2["detalle"]

    dolares = Decimal(detalle["dolares"])
    if dolares > 0:
        return {
            "fecha_cierre": fecha_cierre,
            "estado": "USD_CUENTA_PENDIENTE",
            "motivo": "DOLARES > 0.00 y la cuenta USD no está parametrizada.",
            "partidas": [],
        }

    # atc_aplica=False (ATC BRUTO=0.00, ATC_NO_APLICA) significa que este
    # cierre no tiene componente ATC: el asiento se construye sin las 2
    # líneas ATC_NETO/ATC_COMISION, sin que eso sea NO_ASIENTO. Solo es
    # NO_ASIENTO cuando ATC sí aplica (bruto>0) y no quedó determinado.
    atc_aplica = detalle.get("atc_aplica", True)
    atc_neto = detalle.get("atc_neto")
    atc_comision = detalle.get("atc_comision")
    if atc_aplica and (atc_neto is None or atc_comision is None):
        return {
            "fecha_cierre": fecha_cierre,
            "estado": "NO_ASIENTO",
            "motivo": "ATC no está determinado pese a estado OK.",
            "partidas": [],
        }

    partidas = []
    correcciones_aplicadas = []
    advertencias = list(detalle.get("atc_advertencias") or [])

    partidas.append(_partida(
        cuenta_mayor=_CUENTA_HABER, cargo="0.00", haber=detalle["sfc101_haber"],
        asignacion="SFC101", origen="UNIVERSO_SFC101", sfc_origen="SFC101",
        texto_posicion=_TEXTO_HABER_SFC101,
    ))
    partidas.append(_partida(
        cuenta_mayor=_CUENTA_HABER, cargo="0.00", haber=detalle["sfc102_haber"],
        asignacion="SFC102", origen="UNIVERSO_SFC102", sfc_origen="SFC102",
        texto_posicion=_TEXTO_HABER_SFC102,
    ))

    for v in detalle["vouchers_confirmados"]:
        es_autocorreccion = v["estado"] == "AUTOCORRECCION_0_O"
        # fecha_valor y texto_posicion vienen de la fecha PROPIA del
        # depósito (FECHA DE DEPOSITO), nunca de la fecha bancaria de
        # MACROS (fecha_bancaria sigue existiendo para el cruce, pero ya
        # no se usa aquí). El cruce de vouchers (código+importe contra
        # "Tablas Dinamicas Profesional") no cambia.
        partidas.append(_partida(
            cuenta_mayor=_CUENTA_VOUCHER_ATC, cargo=v["importe"], haber="0.00",
            asignacion=v["codigo_confirmado"], fecha_valor=v.get("fecha_deposito"),
            origen="VOUCHER", sfc_origen=v["sfc"],
            texto_posicion=_texto_voucher(v.get("fecha_deposito")),
            codigo_informado_original=v["codigo_informado"] if es_autocorreccion else None,
        ))
        if es_autocorreccion:
            correcciones_aplicadas.append({
                "tipo": "AUTOCORRECCION_0_O",
                "sfc": v["sfc"],
                "codigo_informado": v["codigo_informado"],
                "codigo_confirmado": v["codigo_confirmado"],
            })

    for ci in detalle["ci_validas"]:
        partidas.append(_partida(
            cuenta_mayor=ci["cuenta_contable"], cargo=ci["importe"], haber="0.00",
            # texto_posicion viene literal de "GLOSA ASIENTO
            # COMUNICACIONES INTERNAS" (nunca se reconstruye desde
            # referencia/N° DE FACTURA ni ninguna otra columna).
            asignacion=ci["asignacion"], texto_posicion=ci.get("glosa"),
            origen="CI", sfc_origen=ci["sfc"],
            # Fecha propia de la CI (columna FECHA2) si existe; None si
            # no la trae la hoja (nunca se usa la fecha del cierre como
            # reemplazo).
            fecha_valor=ci.get("fecha_ci"),
        ))

    if atc_aplica:
        # cuenta_contable/asignacion/texto_detalle solo están presentes
        # cuando el ATC viene de la hoja preconciliada "ATC TIQUIPAYA"
        # (ver _detalle_para_asiento): se usan literalmente, tal como
        # vienen de esa hoja (sección B.3: "usar directamente de la
        # hoja"). En el flujo legado (ATC mensual + cruce contra MACROS)
        # esas claves no existen y el comportamiento histórico se
        # conserva exactamente igual (cuenta fija + asignación calculada).
        # _validar_partidas() (más abajo, sin cambios) sigue exigiendo
        # que ATC_NETO/ATC_COMISION usen _CUENTA_VOUCHER_ATC/
        # _CUENTA_ATC_COMISION: eso es justamente lo que hace cumplir la
        # "cuenta esperada" (sección B.10) también para el ATC
        # preconciliado, sin duplicar la regla — una cuenta distinta en
        # la hoja (fuera de la comisión 110201003, ya cubierta por su
        # propia defensa) bloquea el asiento en vez de aceptarse a ciegas.
        partidas.append(_partida(
            cuenta_mayor=atc_neto.get("cuenta_contable") or _CUENTA_VOUCHER_ATC,
            cargo=atc_neto["importe"], haber="0.00",
            asignacion=atc_neto["codigo_confirmado"], fecha_valor=atc_neto.get("fecha_bancaria"),
            origen="ATC_NETO", sfc_origen=None,
            texto_posicion=atc_neto.get("texto_detalle"),
        ))

        partidas.append(_partida(
            cuenta_mayor=atc_comision.get("cuenta_contable") or _CUENTA_ATC_COMISION,
            cargo=atc_comision["importe"], haber="0.00",
            asignacion=atc_comision.get("asignacion") or _asignacion_comision(fecha_cierre),
            origen="ATC_COMISION", sfc_origen=None,
            texto_posicion=atc_comision.get("texto_detalle"),
        ))

    # ETAPA 8: toda partida debe llegar a SAP con fecha_valor. Prioridad:
    # (A) fecha real propia del origen (CI: FECHA2; VOUCHER: FECHA DE
    # DEPOSITO; ATC preconciliado con fecha bancaria propia) se conserva
    # tal cual, nunca se reemplaza. (B) si la partida no trae una fecha
    # real específica (HABER SFC101/SFC102, ATC sin fecha propia, o
    # cualquier otra partida válida sin fecha_valor), se usa como
    # fallback la fecha del cierre. Nunca se inventa una fecha distinta.
    for p in partidas:
        if not p.get("fecha_valor"):
            p["fecha_valor"] = fecha_cierre

    total_cargo = sum((Decimal(p["cargo"]) for p in partidas), Decimal("0"))
    total_haber = sum((Decimal(p["haber"]) for p in partidas), Decimal("0"))
    diferencia = total_cargo - total_haber

    problemas = _validar_partidas(partidas, total_cargo, total_haber, diferencia)

    # Si el asiento construido no pasa la validación (importes negativos,
    # cargo y haber simultáneos, ALQUILERES colado, cuentas inválidas,
    # etc.) nunca se devuelven partidas utilizables: estado ERROR y
    # partidas vacías, para que ETAPA 6 no pueda serializar nada inválido.
    # Los totales y el diagnóstico se conservan para investigar la causa.
    partidas_salida = partidas if not problemas else []

    return {
        "fecha_cierre": fecha_cierre,
        "sociedad": _SOCIEDAD,
        "centro_beneficio": _CENTRO_BENEFICIO,
        "partidas": partidas_salida,
        "cantidad_partidas": len(partidas_salida),
        "total_cargo": io.money_str(total_cargo),
        "total_haber": io.money_str(total_haber),
        "diferencia": io.money_str(diferencia),
        "correcciones_aplicadas": correcciones_aplicadas,
        "advertencias": advertencias,
        "estado": "OK" if not problemas else "ERROR",
        "problemas": problemas,
    }


# ---------------------------------------------------------------------------
# Optimización PRE-SAP: procesamiento de un lote de cierres del mismo mes
# ---------------------------------------------------------------------------
#
# Únicamente reutiliza aperturas y evita repetir cruces/reglas cuando se
# procesan varios cierres contra el mismo MACROS/ATC mensual. No cambia
# ninguna regla de negocio: cada cierre del lote produce exactamente el
# mismo resultado_v2 y asiento que ejecutar_v2()+construir_asiento()
# llamados individualmente sobre esa misma ruta.

def ejecutar_lote_v2(rutas_cierres, ruta_macros, ruta_atc):
    """Procesa varios cierres del mismo mes reutilizando MACROS y ATC ya
    cargados en memoria.

    - MACROS se abre UNA sola vez para todo el lote.
    - ATC se abre UNA sola vez para todo el lote.
    - Cada CIERRE se abre UNA sola vez.
    - Los cruces/reglas de ETAPA 3-5 se aplican tal cual (mismas funciones
      que usa el flujo individual, vía _ejecutar_v2_sobre_cierre()), sin
      repetirse entre cierres.

    Un fallo técnico al leer MACROS o ATC (archivos compartidos por todo
    el lote) bloquea el lote completo de forma estructurada: sin esos
    índices ningún cierre del lote puede procesarse de forma confiable.

    Un problema puntual de un cierre —bloqueado por excepción, con
    diferencia, USD pendiente, o incluso un error técnico al leer o
    procesar ESE cierre en particular— NUNCA detiene el resto del lote:
    cada cierre conserva su propio resultado_v2, asiento y error de forma
    aislada, sin contaminar a los demás.

    Devuelve:
    {
      "estado": "LOTE_OK" | "LOTE_ERROR_MAESTROS",
      "error": "..."            (solo si LOTE_ERROR_MAESTROS),
      "cantidad": N,
      "cierres": [
        {"ruta": "...", "resultado_v2": {...}, "asiento": {...} | None},
        ...
      ],
    }
    """
    try:
        macros_idx = io.leer_macros_bnb(ruta_macros)   # UNA sola apertura para todo el lote
        atc_idx = io.leer_atc_mensual(ruta_atc)         # UNA sola apertura para todo el lote
    except (ValueError, KeyError) as exc:
        return {
            "estado": "LOTE_ERROR_MAESTROS",
            "error": str(exc),
            "cantidad": 0,
            "cierres": [],
        }

    resultados = []
    for ruta_cierre in rutas_cierres:
        try:
            cierre = io.leer_cierre(ruta_cierre)  # UNA sola apertura por cierre
        except (ValueError, KeyError) as exc:
            resultado_v2 = {
                "fecha": None,
                "estado": "INDETERMINADO",
                "error": str(exc),
                "etapa": "EXTRACCION",
            }
            resultados.append({
                "ruta": ruta_cierre,
                "resultado_v2": resultado_v2,
                "asiento": construir_asiento(resultado_v2),
            })
            continue

        resultado_v2 = _ejecutar_v2_sobre_cierre(cierre, macros_idx, atc_idx)
        resultados.append({
            "ruta": ruta_cierre,
            "resultado_v2": resultado_v2,
            "asiento": construir_asiento(resultado_v2),
        })

    return {
        "estado": "LOTE_OK",
        "cantidad": len(resultados),
        "cierres": resultados,
    }


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Uso: python motor_tiquipaya.py <cierre.xlsm> <macros.xlsm> <atc.xlsx>")
        raise SystemExit(1)

    resumen = ejecutar_v2(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(resumen, ensure_ascii=False, indent=2))

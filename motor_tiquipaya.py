"""
motor_tiquipaya.py — ETAPA 3: cruces determinísticos V2 (Caja Tiquipaya CLOUD).

Orquesta:
  1. VOUCHERS ↔ MACROS BNB (código de asignación + importe exacto)
  2. ATC mensual: NETO + COMISIÓN = ATC BRUTO del cierre
  3. NETO ATC ↔ MACROS BNB (importe exacto)
  4. Validación mínima de CI (cuenta, asignación, formato por banco, ALQUILERES)

NO calcula cuadre final, NO construye asiento, NO genera SAP, NO mueve cierres,
NO marca procesado, NO genera reportes. Claude no procesa filas: todo el
recorrido de filas ocurre aquí, en Python, con Decimal.

Uso:
    python motor_tiquipaya.py <cierre.xlsm> <macros.xlsm> <atc.xlsx>
"""

import sys
import json
from decimal import Decimal

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

    # Buscar NETO en MACROS BNB por importe exacto.
    candidatos = macros_idx["por_importe"].get(io.money_str(neto), [])
    if len(candidatos) == 1:
        m = candidatos[0]
        resultado["estado_match_macros"] = "ATC_MATCH_EXACTO"
        resultado["codigo_encontrado"] = m["codigo"]
        resultado["fecha_bancaria_encontrada"] = m["fecha"]
    elif len(candidatos) == 0:
        resultado["estado_match_macros"] = "ATC_SIN_CANDIDATO"
        resultado["excepcion"] = True
    else:
        resultado["estado_match_macros"] = "ATC_MULTIPLE"
        resultado["excepcion"] = True

    return resultado


# ---------------------------------------------------------------------------
# 4. Validación mínima de Comunicaciones Internas
# ---------------------------------------------------------------------------

def validar_ci(cierre):
    validas = 0
    detalle_validas = []
    bloqueantes = []
    advertencias = []
    alquileres = []

    for ci in cierre["comunicaciones_internas"]:
        if ci["alquileres"]:
            alquileres.append(ci)
            continue  # EXCLUIDO_ALQUILERES: sin validación de cuenta/banco/formato

        problema_bloqueante = None
        if not ci["cuenta_contable"]:
            problema_bloqueante = "CI_CUENTA_FALTANTE"
        elif not ci["asignacion"]:
            problema_bloqueante = "CI_ASIGNACION_FALTANTE"

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
    """
    vouchers = cruzar_vouchers(cierre, macros_idx)
    atc = cruzar_atc(cierre, atc_idx, macros_idx)
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
    CI_OPERATIVAS = CI válidas menos ALQUILERES (alquileres ya excluidos
        del importe operativo por validar_ci, se restan aquí explícitamente
        del total de CI válidas para dejar la fórmula trazable).
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

    ci_operativas = Decimal(cruces["ci"]["importe"]) - Decimal(cruces["ci"]["alquileres_importe"])

    atc_bruto = Decimal(cruces["atc"]["bruto"])

    dolares = Decimal(cierre["sfc101"]["dolares"]) + Decimal(cierre["sfc102"]["dolares"])
    dolares_activo = dolares if dolares > 0 else Decimal("0")

    return {
        "vouchers": io.money_str(vouchers_validos),
        "ci_operativas": io.money_str(ci_operativas),
        "atc_bruto": io.money_str(atc_bruto),
        "dolares": io.money_str(dolares_activo),
    }


def ejecutar_v2(ruta_cierre, ruta_macros, ruta_atc):
    """
    ETAPA 4: orquesta ETAPA 2 (extracción) + ETAPA 3 (cruces) + ETAPA 4
    (universo, ALQUILERES, componentes, recaudación explicada, cuadre)
    en una sola corrida. Cada archivo se abre UNA sola vez.

    Si falta un componente imprescindible (p. ej. el CIERRE no tiene las
    hojas o campos requeridos), el estado resultante es INDETERMINADO en
    lugar de propagar la excepción, para que el llamador reciba siempre
    un resumen estructurado.
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
        }

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

    if excepciones_bloqueantes > 0:
        estado = "BLOQUEADO_EXCEPCION"
    elif Decimal(diferencia) != 0:
        estado = "DIFERENCIA"
    else:
        estado = "OK"

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
        "detalle": _detalle_para_asiento(cierre, cruces, componentes),
    }


def _detalle_para_asiento(cierre, cruces, componentes):
    """Expone, sin recalcular nada, los datos crudos ya producidos por la
    ETAPA 2 (cierre) y la ETAPA 3 (cruces) que la ETAPA 5 necesita para
    construir el asiento: totales HABER por SFC, vouchers ya confirmados,
    CI ya validadas y ATC ya cruzado contra MACROS.
    """
    vouchers_confirmados = [
        {
            "sfc": v["sfc"],
            "importe": v["importe"],
            "codigo_confirmado": v["codigo_encontrado"],
            "codigo_informado": v["codigo_informado"],
            "fecha_bancaria": v.get("fecha_bancaria"),
            "estado": v["estado"],
        }
        for v in cruces["vouchers"]["detalle"]
        if v["estado"] in _ESTADOS_VOUCHER_VALIDOS
    ]

    atc = cruces["atc"]
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
        "sfc101_total": cierre["sfc101"]["total_movimiento"],
        "sfc102_total": cierre["sfc102"]["total_movimiento"],
        "vouchers_confirmados": vouchers_confirmados,
        "ci_validas": cruces["ci"]["detalle_validas"],
        "atc_neto": atc_neto,
        "atc_comision": atc_comision,
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

    if detalle.get("atc_neto") is None or detalle.get("atc_comision") is None:
        return {
            "fecha_cierre": fecha_cierre,
            "estado": "NO_ASIENTO",
            "motivo": "ATC no está determinado pese a estado OK.",
            "partidas": [],
        }

    partidas = []
    correcciones_aplicadas = []

    partidas.append(_partida(
        cuenta_mayor=_CUENTA_HABER, cargo="0.00", haber=detalle["sfc101_total"],
        asignacion="SFC101", origen="UNIVERSO_SFC101", sfc_origen="SFC101",
    ))
    partidas.append(_partida(
        cuenta_mayor=_CUENTA_HABER, cargo="0.00", haber=detalle["sfc102_total"],
        asignacion="SFC102", origen="UNIVERSO_SFC102", sfc_origen="SFC102",
    ))

    for v in detalle["vouchers_confirmados"]:
        es_autocorreccion = v["estado"] == "AUTOCORRECCION_0_O"
        partidas.append(_partida(
            cuenta_mayor=_CUENTA_VOUCHER_ATC, cargo=v["importe"], haber="0.00",
            asignacion=v["codigo_confirmado"], fecha_valor=v.get("fecha_bancaria"),
            origen="VOUCHER", sfc_origen=v["sfc"],
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
            asignacion=ci["asignacion"], texto_posicion=ci.get("referencia"),
            origen="CI", sfc_origen=ci["sfc"],
        ))

    atc_neto = detalle["atc_neto"]
    partidas.append(_partida(
        cuenta_mayor=_CUENTA_VOUCHER_ATC, cargo=atc_neto["importe"], haber="0.00",
        asignacion=atc_neto["codigo_confirmado"], fecha_valor=atc_neto.get("fecha_bancaria"),
        origen="ATC_NETO", sfc_origen=None,
    ))

    atc_comision = detalle["atc_comision"]
    partidas.append(_partida(
        cuenta_mayor=_CUENTA_ATC_COMISION, cargo=atc_comision["importe"], haber="0.00",
        asignacion=_asignacion_comision(fecha_cierre), origen="ATC_COMISION", sfc_origen=None,
    ))

    total_cargo = sum((Decimal(p["cargo"]) for p in partidas), Decimal("0"))
    total_haber = sum((Decimal(p["haber"]) for p in partidas), Decimal("0"))
    diferencia = total_cargo - total_haber

    problemas = _validar_partidas(partidas, total_cargo, total_haber, diferencia)

    return {
        "fecha_cierre": fecha_cierre,
        "sociedad": _SOCIEDAD,
        "centro_beneficio": _CENTRO_BENEFICIO,
        "partidas": partidas,
        "cantidad_partidas": len(partidas),
        "total_cargo": io.money_str(total_cargo),
        "total_haber": io.money_str(total_haber),
        "diferencia": io.money_str(diferencia),
        "correcciones_aplicadas": correcciones_aplicadas,
        "estado": "OK" if not problemas else "ERROR",
        "problemas": problemas,
    }


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Uso: python motor_tiquipaya.py <cierre.xlsm> <macros.xlsm> <atc.xlsx>")
        raise SystemExit(1)

    resumen = ejecutar_v2(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(resumen, ensure_ascii=False, indent=2))

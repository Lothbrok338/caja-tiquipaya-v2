"""candidatos_voucher.py — Candidatos en MACROS para un deposito cuyo voucher NO se encontro (asignacion + importe).

SOLO DIAGNOSTICO. No corrige nada, no cambia ninguna regla de normalizacion del Control 5 y no toca el cierre: cuando la
busqueda exacta por (asignacion + importe) falla, este modulo mira en MACROS que registros PODRIAN ser el deposito
(p. ej. porque el cajero escribio mal la fecha o la asignacion) y se lo muestra a una persona para que decida.

Busqueda (sobre los `registros` de MACROS, ver macros_vouchers.leer_indice_macros):
  1. importe EXACTO;
  2. misma cuenta/banco y misma caja/SFC (si el dato existe en ambos lados);
  3. fecha esperada del deposito con ventana de +-1 dia. Fecha esperada = dia siguiente al cierre (si cae en domingo,
     el lunes). Es una heuristica propia del auditor, independiente del motor CAJAS GABO;
  4. si no hay ningun candidato FUERTE (los cuatro criterios) se revisa tambien el importe exacto en otras fechas.

Veredicto:
  PROBABLE   UN unico candidato y ese candidato es FUERTE (importe exacto + misma cuenta + misma caja/SFC + fecha esperada
             dentro de +-1 dia). Es la unica situacion que merece este veredicto;
  POSIBLE    UN unico candidato que NO es fuerte: fuera de +-1 dia, coincidencia parcial (difiere la cuenta o la caja) o
             algun criterio que no se pudo verificar por falta de datos. Requiere revision manual;
  VARIOS     mas de un candidato razonable (aunque alguno sea fuerte): no se puede elegir automaticamente;
  NINGUNO    ningun candidato.
Un candidato es "razonable" si tiene el importe exacto y no difiere a la vez en cuenta Y caja. Un dato NO VERIFICABLE
(falta en el cierre o en MACROS) no descarta al candidato, pero impide que sea FUERTE.
"""
import datetime
import re

import catalogo_bancos as cb
import macros_vouchers as mv

PROBABLE = "CANDIDATO PROBABLE"
POSIBLE = "CANDIDATO POSIBLE — REVISIÓN MANUAL"
VARIOS = "VARIOS CANDIDATOS — REVISIÓN MANUAL"
NINGUNO = "SIN CANDIDATOS EN MACROS"

FUERTE = "FUERTE"                    # importe + cuenta + caja + fecha dentro de la ventana
PARCIAL = "PARCIAL"                  # importe exacto y fecha en la ventana, pero difiere la cuenta o la caja (o no es verificable)
FUERA_DE_VENTANA = "FUERA_DE_VENTANA"  # importe exacto, en otra fecha del mismo MACROS

VENTANA_DIAS = 1
MAX_CANDIDATOS = 8
_ORDEN = {FUERTE: 0, PARCIAL: 1, FUERA_DE_VENTANA: 2}


def _fmt(d):
    return d.strftime("%d/%m/%Y") if d else None


def fecha_esperada(fecha_cierre):
    """Dia siguiente al cierre; si es domingo, el lunes. None si no se conoce la fecha del cierre."""
    if not fecha_cierre:
        return None
    d = fecha_cierre + datetime.timedelta(days=1)
    while d.weekday() == 6:
        d += datetime.timedelta(days=1)
    return d


def _invertida(d):
    """La fecha con dia y mes intercambiados, o None si no existe / es igual."""
    if not d or d.day > 12 or d.day == d.month:
        return None
    try:
        return datetime.date(d.year, d.day, d.month)
    except ValueError:
        return None


def cuenta_de_banco(valor):
    """Cuenta contable a partir de lo escrito en la columna BANCO del cierre: el numero de cuenta tal cual, o la cuenta de la
    tabla oficial si se escribio un nombre de banco (p. ej. 'BNB MN'). None si no se puede determinar."""
    if valor is None:
        return None
    t = str(valor).strip()
    if not t:
        return None
    if re.fullmatch(r"[0-9]+", t):
        return t
    return cb.interpretar_banco(t).get("cuenta_esperada")


def _tri(a, b):
    """True/False si ambos datos existen; None si alguno falta (no verificable)."""
    if not a or not b:
        return None
    return a == b


def macros_hasta(registros):
    fechas = [r["fecha"] for r in registros if r.get("fecha")]
    return max(fechas) if fechas else None


def buscar(registros, importe, cuenta, sfc, fecha_declarada, fecha_cierre, asignacion=None):
    """Busca candidatos para un deposito sin voucher exacto. `registros`: lista de dicts
    {fecha: date|None, importe: '0.00', codigo, cuenta, caja} de MACROS. Devuelve un dict serializable (solo texto/numeros)."""
    esperada = fecha_esperada(fecha_cierre)
    ventana = (esperada - datetime.timedelta(days=VENTANA_DIAS), esperada + datetime.timedelta(days=VENTANA_DIAS)) if esperada else None
    sfc_n = mv.normalizar_codigo(sfc) or None
    cuenta_n = str(cuenta).strip() if cuenta else None
    codigo_dec = mv.normalizar_codigo(asignacion) or None
    inv = _invertida(fecha_declarada)

    iguales = [r for r in registros if r.get("importe") == importe]
    hallados = []
    for r in iguales:
        cta_ok = _tri(cuenta_n, r.get("cuenta"))
        caja_ok = _tri(sfc_n, r.get("caja"))
        if cta_ok is False and caja_ok is False:
            continue                       # solo coincide el importe: no es un candidato razonable
        f = r.get("fecha")
        en_ventana = bool(ventana and f and ventana[0] <= f <= ventana[1])
        if en_ventana and cta_ok and caja_ok:
            fuerza = FUERTE
        elif en_ventana:
            fuerza = PARCIAL
        else:
            fuerza = FUERA_DE_VENTANA
        hallados.append((r, cta_ok, caja_ok, en_ventana, fuerza))

    if not any(h[4] == FUERTE for h in hallados):
        elegidos = hallados                # sin candidato fuerte: tambien cuentan las otras fechas del mismo MACROS
    else:
        elegidos = [h for h in hallados if h[4] != FUERA_DE_VENTANA]

    def distancia(h):
        f = h[0].get("fecha")
        return abs((f - esperada).days) if (f and esperada) else 10 ** 6

    elegidos.sort(key=lambda h: (_ORDEN[h[4]], distancia(h), h[0].get("fecha") or datetime.date.max))

    candidatos = []
    for r, cta_ok, caja_ok, en_ventana, fuerza in elegidos:
        f = r.get("fecha")
        coin, dif, no_verif, difiere = ["Importe exacto"], [], [], []
        if cta_ok:
            coin.append("Cuenta %s" % r["cuenta"])
        elif cta_ok is False:
            dif.append("Cuenta distinta (cierre: %s; MACROS: %s)" % (cuenta_n, r["cuenta"]))
            difiere.append("cuenta")
        else:
            dif.append("Cuenta no verificable")
            no_verif.append("cuenta")
        if caja_ok:
            coin.append("Caja %s" % r["caja"])
        elif caja_ok is False:
            dif.append("Caja distinta (cierre: %s; MACROS: %s)" % (sfc_n, r["caja"]))
            difiere.append("caja")
        else:
            dif.append("Caja no verificable")
            no_verif.append("caja")
        if en_ventana:
            coin.append("Fecha dentro de la ventana esperada (%s, ±%d día)" % (_fmt(esperada), VENTANA_DIAS))
        elif f is None:
            dif.append("El voucher de MACROS no tiene fecha válida")
            no_verif.append("fecha")
        elif ventana:
            dif.append("Fecha fuera de la ventana esperada (%s a %s)" % (_fmt(ventana[0]), _fmt(ventana[1])))
            difiere.append("fecha")
        else:
            dif.append("Fecha esperada no verificable (se desconoce la fecha del cierre)")
            no_verif.append("fecha")
        if f and inv and f == inv:
            coin.append("Día y mes de la fecha declarada invertidos (cierre: %s; MACROS: %s)" % (_fmt(fecha_declarada), _fmt(f)))
        if f and fecha_declarada and f != fecha_declarada:
            dif.append("Fecha distinta (cierre: %s; MACROS: %s)" % (_fmt(fecha_declarada), _fmt(f)))
        if len(iguales) == 1:
            coin.append("Importe único en MACROS")
        if not codigo_dec:
            dif.append("El cierre no declara asignación")
        elif codigo_dec != r.get("codigo"):
            dif.append("Asignación distinta (cierre: %s; MACROS: %s)" % (codigo_dec, r.get("codigo")))
        candidatos.append({"fecha": _fmt(f), "importe": r["importe"], "asignacion": r.get("codigo"), "cuenta": r.get("cuenta"),
                           "caja": r.get("caja"), "fuerza": fuerza, "coincidencias": coin, "diferencias": dif,
                           "no_verificable": no_verif, "difiere": difiere,
                           "fecha_invertida": bool(f and inv and f == inv),
                           "fecha_distinta": bool(f and fecha_declarada and f != fecha_declarada),
                           "asignacion_distinta": bool(codigo_dec and codigo_dec != r.get("codigo"))})

    if not candidatos:
        veredicto, fuerza = NINGUNO, None
    elif len(candidatos) > 1:
        veredicto, fuerza = VARIOS, None
    elif candidatos[0]["fuerza"] == FUERTE:
        veredicto, fuerza = PROBABLE, FUERTE
    else:
        veredicto, fuerza = POSIBLE, candidatos[0]["fuerza"]

    # la asignacion escrita en el cierre puede existir en MACROS como otro abono (pista de un error de copia)
    asignacion_en_macros = []
    if codigo_dec:
        for r in registros:
            if r.get("codigo") == codigo_dec:
                asignacion_en_macros.append({"fecha": _fmt(r.get("fecha")), "importe": r["importe"], "caja": r.get("caja")})

    return {
        "veredicto": veredicto,
        "fuerza": fuerza,
        "declarado": {"importe": importe, "fecha": _fmt(fecha_declarada), "asignacion": codigo_dec, "cuenta": cuenta_n, "sfc": sfc_n},
        "fecha_esperada": _fmt(esperada),
        "ventana": [_fmt(ventana[0]), _fmt(ventana[1])] if ventana else None,
        "macros_hasta": _fmt(macros_hasta(registros)),
        "importe_en_macros": len(iguales),
        "candidatos": candidatos[:MAX_CANDIDATOS],
        "omitidos": max(0, len(candidatos) - MAX_CANDIDATOS),
        "asignacion_en_macros": asignacion_en_macros[:3],
    }

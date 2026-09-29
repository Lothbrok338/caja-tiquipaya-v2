"""v3/avance_caja.py — "Procesado continuo hasta" de una caja (solo lectura).

Responde, para la interfaz V3, hasta qué fecha llegó de forma CONTINUA el
procesamiento oficial de una caja, distinguiendo huecos: con 09/09 y 10/09
procesados, 11/09 pendiente y 12/09 procesado, el avance continuo es 10/09
(nunca 12/09, que es solo el último cierre existente).

Criterio oficial de "procesado": el MISMO que ya usa GLOBAL para decidir
qué días del periodo tienen cierre oficial (ver
v3/consolidador_mensual_v3.descubrir_sap_oficiales_del_mes): que exista en
la carpeta SAP oficial de la caja el SAP diario publicado por 06B
(`SAP_<prefijo>_DD-MM-YYYY.xlsx`; para TIQUIPAYA también el legacy
`SAP_DD-MM-YYYY.xlsx`). El reconocimiento del nombre se delega TAL CUAL en
`_fecha_y_origen_desde_nombre_sap`, que es config-driven (prefijo de
`config_cajas.CajaConfig`): una caja futura no necesita ningún código nuevo
aquí, solo su entrada en config_cajas.CAJAS.

Este módulo NO toca Drive, el motor, el precheck, la publicación ni las
reglas contables: n8n (workflow "AVANCE CAJA", solo lectura) lista los
nombres de archivo de la carpeta SAP y Python, única autoridad de reglas,
decide qué fechas cuentan y dónde se corta la continuidad.

Ventana de continuidad: desde el día 1 del mes de la última fecha procesada
hasta esa última fecha (el mismo alcance mensual con que GLOBAL calcula
`fechas_faltantes`). Cada día calendario cuenta: un día sin SAP oficial
dentro de la ventana es un pendiente y corta la continuidad.
"""

import datetime

import config_cajas as cfg
from v3.consolidador_mensual_v3 import _fecha_y_origen_desde_nombre_sap


def fechas_procesadas(caja, nombres_archivos):
    """Conjunto de `datetime.date` con SAP diario oficial para `caja`.
    Nombres no reconocidos (otra caja, SAP_GLOBAL_*, temporales, fechas
    imposibles) simplemente no cuentan."""
    caja = cfg.resolver_caja(caja)
    fechas = set()
    for nombre in nombres_archivos or []:
        if not isinstance(nombre, str):
            continue
        try:
            fecha, _origen = _fecha_y_origen_desde_nombre_sap(nombre, caja)
        except ValueError:  # p. ej. SAP_TIQ_31-02-2026.xlsx: no es una fecha real
            continue
        if fecha is not None:
            fechas.add(fecha)
    return fechas


def calcular_avance(caja, nombres_archivos):
    """Avance de `caja` a partir de los nombres de archivo de su carpeta SAP
    oficial. Devuelve fechas en ISO (YYYY-MM-DD) o None:

      procesado_continuo_hasta  último día de la racha continua que arranca
                                el día 1 de la ventana (None si ese día 1 no
                                está procesado o no hay ningún cierre).
      ultimo_cierre_existente   fecha máxima con SAP oficial (informativo).
      pendientes                cantidad de días sin SAP oficial dentro de la
                                ventana [desde, ultimo_cierre_existente].
      primer_pendiente          primer día pendiente (None si no hay).
      desde                     inicio de la ventana (día 1 del mes del
                                último cierre existente).
    """
    caja = cfg.resolver_caja(caja)
    fechas = fechas_procesadas(caja, nombres_archivos)

    resultado = {
        "disponible": True, "caja": caja.codigo,
        "procesado_continuo_hasta": None, "ultimo_cierre_existente": None,
        "pendientes": 0, "primer_pendiente": None, "desde": None,
        "dias_procesados": len(fechas),
    }
    if not fechas:
        return resultado

    ultimo = max(fechas)
    desde = ultimo.replace(day=1)
    un_dia = datetime.timedelta(days=1)

    continuo_hasta = None
    pendientes = []
    cortada = False
    dia = desde
    while dia <= ultimo:
        if dia in fechas:
            if not cortada:
                continuo_hasta = dia
        else:
            cortada = True
            pendientes.append(dia)
        dia += un_dia

    resultado.update({
        "procesado_continuo_hasta": continuo_hasta.isoformat() if continuo_hasta else None,
        "ultimo_cierre_existente": ultimo.isoformat(),
        "pendientes": len(pendientes),
        "primer_pendiente": pendientes[0].isoformat() if pendientes else None,
        "desde": desde.isoformat(),
    })
    return resultado

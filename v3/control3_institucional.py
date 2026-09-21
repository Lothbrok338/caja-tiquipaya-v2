"""v3/control3_institucional.py — adaptador CONTROL 3 institucional.

Lee SIMULTÁNEAMENTE los dos GLOBAL por caja (SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx
y SAP_GLOBAL_AME_<MES>_<AÑO>.xlsx), los combina SOLO EN MEMORIA (nunca crea
ni modifica un GLOBAL institucional) y acumula CxC/CxP agrupando por la
llave CUENTA+ASIGNACION ya existente en control_cxc_cxp.py — así una CxP en
AME y una CxC en TIQ con la MISMA cuenta+asignación se compensan en un
único saldo institucional.

NUNCA reescribe control_cxc_cxp.py: reutiliza tal cual leer_partidas_global,
clasificar_partidas, agrupar_movimientos_mes, _actualizar_fila,
_construir_filas_excel, guardar_control_xlsx, cargar_historico/
guardar_historico y el libro de periodos (_cargar_libro_periodos/
_guardar_libro_periodos/_estado_idempotencia). La única novedad es la
combinación TIQ+AME en memoria y la idempotencia por el PAR
sha256(TIQ)+sha256(AME) en orden fijo TIQ→AME, reutilizando el MISMO
mecanismo de libro de periodos (que ya es agnóstico a qué string sea el
"sha256_global" que se le pase)."""

import datetime
import json
import os
from decimal import Decimal

import config_cajas as cfg
import control_cxc_cxp as ctrl3

CAJA_TIQ = cfg.TIQUIPAYA.codigo
CAJA_AME = cfg.AMERICA.codigo


def nombre_historico_institucional():
    return "HISTORICO_CXC_CXP.csv"


def nombre_reporte_institucional(periodo):
    return f"CONTROL_CXC_CXP_INSTITUCIONAL_{periodo}.xlsx"


def nombre_detalle_institucional(periodo):
    return f"CONTROL_CXC_CXP_INSTITUCIONAL_{periodo}.json"


def _leer_candidatas_tagged(ruta_global, caja_codigo):
    nombre = os.path.basename(ruta_global)
    partidas = ctrl3.leer_partidas_global(ruta_global)
    for p in partidas:
        p["caja"] = caja_codigo
        p["archivo_origen"] = nombre
        p["fila_origen"] = p["fila_sap"]
    return ctrl3.clasificar_partidas(partidas)


def _validar_periodos(nombre_tiq, nombre_ame):
    periodo_tiq = ctrl3._derivar_periodo(nombre_tiq, cfg.TIQUIPAYA)
    periodo_ame = ctrl3._derivar_periodo(nombre_ame, cfg.AMERICA)
    if periodo_tiq is None or periodo_ame is None:
        return None, {
            "estado": "ERROR_TECNICO",
            "problemas": ["GLOBAL_NOMBRE_NO_CANONICO"],
            "archivo_global_tiq": nombre_tiq,
            "archivo_global_ame": nombre_ame,
        }
    if periodo_tiq != periodo_ame:
        return None, {
            "estado": "ERROR_TECNICO",
            "problemas": ["PERIODOS_DISTINTOS_TIQ_AME"],
            "periodo_tiq": periodo_tiq,
            "periodo_ame": periodo_ame,
        }
    return periodo_tiq, None


def _trazabilidad_por_clave(candidatas):
    """CAJA/ARCHIVO_ORIGEN/FILA_ORIGEN de cada movimiento que contribuyó a
    la llave CUENTA+ASIGNACION este periodo — informativo, nunca se
    escribe dentro del histórico permanente (que conserva su esquema V2
    sin cambios) ni cambia el cálculo de saldo/estado."""
    origenes = {}
    for p in candidatas:
        clave = (p["cuenta_mayor"], p["asignacion"])
        origenes.setdefault(clave, []).append({
            "caja": p["caja"], "archivo_origen": p["archivo_origen"], "fila_origen": p["fila_origen"],
        })
    return origenes


def ejecutar_control3_institucional(ruta_global_tiq, ruta_global_ame, ruta_historico_institucional,
                                     ruta_salida_xlsx=None, ruta_salida_json=None, dry_run=False):
    """CONTROL 3 institucional. Nunca modifica ningún GLOBAL (solo
    lectura). Idempotente por el PAR (sha256(TIQ), sha256(AME)), orden fijo
    TIQ→AME: si cualquiera de los dos GLOBAL cambia, el periodo pasa a
    GLOBAL_MODIFICADO_REQUIERE_REVISION."""
    if not ruta_global_tiq or not os.path.isfile(ruta_global_tiq):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_TIQ_NO_ENCONTRADO"]}
    if not ruta_global_ame or not os.path.isfile(ruta_global_ame):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_AME_NO_ENCONTRADO"]}

    nombre_tiq = os.path.basename(ruta_global_tiq)
    nombre_ame = os.path.basename(ruta_global_ame)
    periodo, error = _validar_periodos(nombre_tiq, nombre_ame)
    if error:
        return error

    sha_tiq = ctrl3._hash_archivo(ruta_global_tiq)
    sha_ame = ctrl3._hash_archivo(ruta_global_ame)
    sha_par = f"{sha_tiq}|{sha_ame}"  # orden fijo TIQ->AME

    historico = ctrl3.cargar_historico(ruta_historico_institucional)
    libro_periodos = ctrl3._cargar_libro_periodos(ruta_historico_institucional)
    ahora = datetime.datetime.now().isoformat(timespec="seconds")

    estado_idemp = ctrl3._estado_idempotencia(historico, libro_periodos, periodo, sha_par)

    if estado_idemp == "RECUPERAR_APLICADO":
        if not dry_run:
            libro_periodos[periodo] = {
                "sha256_global": sha_par, "estado": ctrl3._PERIODO_APLICADO,
                "fecha_ejecucion": ahora, "recuperado": True,
            }
            ctrl3._guardar_libro_periodos(ruta_historico_institucional, libro_periodos)
        estado_idemp = "YA_PROCESADO_SIN_CAMBIOS"
    elif estado_idemp == "RECUPERAR_PENDIENTE":
        estado_idemp = None

    if estado_idemp == "GLOBAL_MODIFICADO_REQUIERE_REVISION":
        return {
            "estado": estado_idemp,
            "periodo": periodo,
            "sha_par": sha_par,
            "archivo_global_tiq": nombre_tiq,
            "archivo_global_ame": nombre_ame,
            "mensaje": (
                "Ya existe un histórico institucional para este periodo con un "
                "PAR de SHA-256 (TIQ,AME) distinto al actual. Requiere decisión "
                "humana; el GLOBAL nunca se modifica."
            ),
            "dry_run": dry_run,
            "historico_actualizado": False,
        }

    if estado_idemp == "YA_PROCESADO_SIN_CAMBIOS":
        return {
            "estado": estado_idemp,
            "periodo": periodo,
            "sha_par": sha_par,
            "archivo_global_tiq": nombre_tiq,
            "archivo_global_ame": nombre_ame,
            "mensaje": "Este PAR GLOBAL TIQ/AME ya fue acumulado. No se vuelve a acumular.",
            "dry_run": dry_run,
            "historico_actualizado": False,
        }

    try:
        candidatas_tiq, faltantes_tiq = _leer_candidatas_tagged(ruta_global_tiq, CAJA_TIQ)
        candidatas_ame, faltantes_ame = _leer_candidatas_tagged(ruta_global_ame, CAJA_AME)
    except ctrl3.HojaNoEncontradaError:
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_HOJA_1_NO_ENCONTRADA"]}
    except Exception as exc:  # noqa: BLE001 — GLOBAL ilegible, se reporta y se detiene
        return {"estado": "ERROR_TECNICO", "problemas": [f"GLOBAL_ILEGIBLE:{exc}"]}

    candidatas = candidatas_tiq + candidatas_ame  # orden fijo TIQ->AME
    faltantes = faltantes_tiq + faltantes_ame
    grupos_mes = ctrl3.agrupar_movimientos_mes(candidatas)
    trazabilidad = _trazabilidad_por_clave(candidatas)

    claves = sorted(set(historico.keys()) | set(grupos_mes.keys()))
    nuevo_historico = {}
    for clave in claves:
        cuenta, _asignacion = clave
        tipo_cuenta, tipo_label = ctrl3._CUENTAS_CONTROL[cuenta]
        prev_row = historico.get(clave)
        mov = grupos_mes.get(clave)
        debe_mes = mov["debe"] if mov else Decimal("0.00")
        haber_mes = mov["haber"] if mov else Decimal("0.00")
        nuevo_historico[clave] = ctrl3._actualizar_fila(
            clave, tipo_cuenta, tipo_label, prev_row, debe_mes, haber_mes, periodo, sha_par, ahora,
        )

    abiertas = sum(1 for f in nuevo_historico.values() if f["estado"] == ctrl3._ESTADO_ABIERTO)
    cerradas = sum(1 for f in nuevo_historico.values() if f["estado"] == ctrl3._ESTADO_CERRADO)
    revisar = sum(1 for f in nuevo_historico.values() if f["estado"] == ctrl3._ESTADO_REVISAR)

    resumen = {
        "estado": "OK",
        "periodo": periodo,
        "sha_par": sha_par,
        "archivo_global_tiq": nombre_tiq,
        "archivo_global_ame": nombre_ame,
        "fecha_ejecucion": ahora,
        "llaves_evaluadas": len(grupos_mes),
        "abiertas": abiertas,
        "cerradas": cerradas,
        "revisar": revisar,
        "asignaciones_faltantes": len(faltantes),
        "detalle_asignaciones_faltantes": faltantes,
        "trazabilidad_origen": {
            f"{cuenta}|{asignacion}": origenes for (cuenta, asignacion), origenes in trazabilidad.items()
        },
        "dry_run": dry_run,
        "historico_actualizado": False,
        "archivo_control_xlsx": None,
        "archivo_control_json": None,
    }

    if not dry_run:
        libro_periodos[periodo] = {
            "sha256_global": sha_par, "estado": ctrl3._PERIODO_PENDIENTE, "fecha_inicio": ahora,
        }
        ctrl3._guardar_libro_periodos(ruta_historico_institucional, libro_periodos)

        ctrl3.guardar_historico(ruta_historico_institucional, nuevo_historico)

        libro_periodos[periodo] = {
            "sha256_global": sha_par, "estado": ctrl3._PERIODO_APLICADO, "fecha_ejecucion": ahora,
        }
        ctrl3._guardar_libro_periodos(ruta_historico_institucional, libro_periodos)
        resumen["historico_actualizado"] = True

        if ruta_salida_xlsx:
            filas_excel = ctrl3._construir_filas_excel(nuevo_historico, grupos_mes, periodo, faltantes)
            ctrl3.guardar_control_xlsx(ruta_salida_xlsx, filas_excel)
            resumen["archivo_control_xlsx"] = ruta_salida_xlsx
        if ruta_salida_json:
            resumen["archivo_control_json"] = ruta_salida_json
            with open(ruta_salida_json, "w", encoding="utf-8") as f:
                json.dump(resumen, f, ensure_ascii=False, indent=2, default=str)

    return resumen

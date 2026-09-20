"""
config_drive_oficial.py — Resolución centralizada de destinos Google Drive
para la PUBLICACION OFICIAL (n8n "06B PUBLICACION OFICIAL" y "PREFLIGHT
OFICIAL") y para el CIERRE MENSUAL (n8n "BACKEND DEV" · /global, /control1,
/control3), por CAJA.

Este módulo es la fuente de verdad EXPLÍCITA que reproducen línea a línea:
  - el nodo Code "RESOLVER - Destinos Drive por caja" (06B / PREFLIGHT
    OFICIAL) para los 5 destinos DIARIOS (`resolver_destinos_drive`);
  - los nodos Code "RESOLVER carpeta SAP oficial" / "RESOLVER control1
    (periodo y carpetas)" / "RESOLVER control3 (periodo y carpetas)"
    (BACKEND DEV) para los 4 destinos MENSUALES + SAP reutilizado
    (`resolver_destinos_drive_mensual`).
(mismo patrón que tests_v3/n8n_publicacion_oficial/logic_reference.js y
tests_v3/n8n_publicacion_mensual/logic_reference.js frente a los nodos de
idempotencia): los nodos Code de n8n corren en un sandbox sin acceso al
filesystem del proyecto, así que el jsCode embebido es, por fuerza, la
única copia que realmente se ejecuta contra Drive. Este módulo no lee
archivos, no llama a Drive y no conoce el motor contable.

TIQUIPAYA conserva los folder IDs reales ya en uso en producción
(snapshots/v3-final, FASE 11A.1/11A.2/12E), sin cambios: son los defaults
que se usan cuando la variable de entorno DRIVE_*_TIQ correspondiente no
está definida.

AMERICA todavía no tiene carpetas reales creadas en Drive: sus variables
DRIVE_*_AME quedan explícitamente SIN default. Resolverlas sin haberlas
configurado FALLA CERRADO (DRIVE_AME_PENDIENTE) -- nunca se inventan ni se
reutilizan los folder IDs de TIQUIPAYA.
"""

import os

import config_cajas as cfg

# Folder IDs históricos de TIQUIPAYA (idénticos a los que 06B/PREFLIGHT
# tenían hardcodeados antes de este cambio).
_TIQ_DEFAULTS = {
    "entrada": "1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1",
    "sap": "1mid4gUHnCmZbISlsAYMwWta3RudTSE13",
    "resultado": "16Z7Uhf-NgiZ6YuqWLnReaIozRIiOg5HO",
    "procesados": "1BkNC6lnonMM7YeWDKck-TM8WTyY2BJJP",
    "marker": "1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu",
}

DESTINOS = ("entrada", "sap", "resultado", "procesados", "marker")


def nombre_variable_entorno(caja, destino):
    """'DRIVE_<DESTINO>_<TIQ|AME>' -- el mismo nombre que construye el nodo
    Code de n8n (const envVar = 'DRIVE_' + clave.toUpperCase() + '_' + ...)."""
    caja = cfg.resolver_caja(caja)
    sufijo = "AME" if caja.codigo == "america" else "TIQ"
    return f"DRIVE_{destino.upper()}_{sufijo}"


def _resolver_destino(caja, destino, entorno, defaults_tiq):
    """Un único destino -> folder ID. Reutilizado por
    `resolver_destinos_drive` (5 destinos DIARIOS) y por
    `resolver_destinos_drive_mensual` (4 destinos MENSUALES + SAP
    reutilizado), para que ninguno de los dos falle por una variable de
    entorno que no le corresponde (p.ej. el mensual nunca debe fallar por
    DRIVE_ENTRADA_AME, que no usa)."""
    env_var = nombre_variable_entorno(caja, destino)
    valor = entorno.get(env_var)
    if valor:
        return valor
    if caja.codigo == "tiquipaya":
        return defaults_tiq[destino]
    raise ValueError(
        f"DRIVE_AME_PENDIENTE: falta configurar {env_var} "
        f"(carpeta '{destino}' de CAJA AMERICA todavia no existe en Drive)."
    )


def resolver_destinos_drive(caja=None, entorno=None):
    """Devuelve {entrada, sap, resultado, procesados, marker} -> folder ID,
    para la caja dada. `entorno` (por defecto os.environ) permite probar
    sin tocar variables reales del proceso.

    FALLA CERRADO: si la caja es AMERICA y una variable DRIVE_*_AME no está
    configurada, se lanza ValueError -- nunca se cae al folder de TIQ."""
    caja = cfg.resolver_caja(caja)
    entorno = os.environ if entorno is None else entorno

    return {destino: _resolver_destino(caja, destino, entorno, _TIQ_DEFAULTS) for destino in DESTINOS}


# Folder IDs históricos de TIQUIPAYA para el CIERRE MENSUAL (idénticos a los
# ya hardcodeados en los nodos "RESOLVER carpeta SAP oficial" / "RESOLVER
# control1 (periodo y carpetas)" / "RESOLVER control3 (periodo y carpetas)"
# de snapshots/v3-final/aLs1f3GMqswbaENA_backend_dev.json antes de este
# cambio). "sap" NO va aquí: el mensual reutiliza el mismo destino "sap" ya
# parametrizado por `resolver_destinos_drive` (_TIQ_DEFAULTS["sap"]).
_MENSUAL_TIQ_DEFAULTS = {
    "controles": "1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB",
    "global": "1KREzDpgptWRwuArA1qYco49rplOEeeNU",
    "control1": "1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk",
    "control3": "15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_",
}

DESTINOS_MENSUAL = ("controles", "global", "control1", "control3")


def resolver_destinos_drive_mensual(caja=None, entorno=None):
    """Devuelve {controles, global, control1, control3, sap} -> folder ID
    para el CIERRE MENSUAL (GLOBAL + CONTROL1 + CONTROL3), para la caja
    dada. `entorno` (por defecto os.environ) permite probar sin tocar
    variables reales del proceso.

    `sap` NO tiene su propio default/variable aquí: se resuelve con la
    MISMA variable de entorno (DRIVE_SAP_TIQ/DRIVE_SAP_AME) y el MISMO
    default histórico de TIQUIPAYA que usa la publicación oficial DIARIA
    (`resolver_destinos_drive`) -- es la misma carpeta física, nunca una
    copia independiente.

    FALLA CERRADO: si la caja es AMERICA y una variable DRIVE_*_AME
    (incluida DRIVE_SAP_AME) no está configurada, se lanza ValueError --
    nunca se cae al folder de TIQUIPAYA ni al de otro destino."""
    caja = cfg.resolver_caja(caja)
    entorno = os.environ if entorno is None else entorno

    destinos = {
        destino: _resolver_destino(caja, destino, entorno, _MENSUAL_TIQ_DEFAULTS)
        for destino in DESTINOS_MENSUAL
    }
    destinos["sap"] = _resolver_destino(caja, "sap", entorno, _TIQ_DEFAULTS)
    return destinos


_PREFIJOS_ESPERADOS = {
    "tiquipaya": ("SAP_TIQ_", "SAP_GLOBAL_TIQ_", "RESULTADO_TIQ_"),
    "america": ("SAP_AME_", "SAP_GLOBAL_AME_", "RESULTADO_AME_"),
}


def validar_prefijo_archivo(caja, nombre_archivo):
    """FAIL CLOSED: si `nombre_archivo` lleva el prefijo canónico de OTRA
    caja (SAP_/SAP_GLOBAL_/RESULTADO_ TIQ vs AME), se rechaza. Un nombre sin
    ninguno de los prefijos reconocidos (p. ej. el cierre original, que no
    es un SAP ni un RESULTADO) no es responsabilidad de este validador y no
    hace nada."""
    caja = cfg.resolver_caja(caja)
    if not nombre_archivo:
        return

    prefijos_propios = _PREFIJOS_ESPERADOS[caja.codigo]
    if any(nombre_archivo.startswith(p) for p in prefijos_propios):
        return

    for otra_caja, prefijos_otra in _PREFIJOS_ESPERADOS.items():
        if otra_caja == caja.codigo:
            continue
        if any(nombre_archivo.startswith(p) for p in prefijos_otra):
            raise ValueError(
                f"PREFIJO_CAJA_NO_COINCIDE: '{nombre_archivo}' tiene "
                f"prefijo de {otra_caja.upper()} pero se esta publicando "
                f"como {caja.codigo.upper()}."
            )

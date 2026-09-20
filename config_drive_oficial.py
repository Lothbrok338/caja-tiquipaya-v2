"""
config_drive_oficial.py — Resolución centralizada de destinos Google Drive
para la PUBLICACION OFICIAL (n8n "06B PUBLICACION OFICIAL" y "PREFLIGHT
OFICIAL"), por CAJA.

Este módulo es la fuente de verdad EXPLÍCITA que el nodo Code "RESOLVER -
Destinos Drive por caja" de ambos workflows reproduce línea a línea (mismo
patrón que tests_v3/n8n_publicacion_oficial/logic_reference.js frente a los
nodos de idempotencia): los nodos Code de n8n corren en un sandbox sin
acceso al filesystem del proyecto, así que el jsCode embebido es, por
fuerza, la única copia que realmente se ejecuta contra Drive. Este módulo
no lee archivos, no llama a Drive y no conoce el motor contable.

TIQUIPAYA conserva los 5 folder IDs reales ya en uso en producción
(snapshots/v3-final, FASE 11A.1/11A.2), sin cambios: son los defaults que
se usan cuando la variable de entorno DRIVE_*_TIQ correspondiente no está
definida.

AMERICA todavía no tiene carpetas reales creadas en Drive: sus 5 variables
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


def resolver_destinos_drive(caja=None, entorno=None):
    """Devuelve {entrada, sap, resultado, procesados, marker} -> folder ID,
    para la caja dada. `entorno` (por defecto os.environ) permite probar
    sin tocar variables reales del proceso.

    FALLA CERRADO: si la caja es AMERICA y una variable DRIVE_*_AME no está
    configurada, se lanza ValueError -- nunca se cae al folder de TIQ."""
    caja = cfg.resolver_caja(caja)
    entorno = os.environ if entorno is None else entorno

    destinos = {}
    for destino in DESTINOS:
        env_var = nombre_variable_entorno(caja, destino)
        valor = entorno.get(env_var)
        if valor:
            destinos[destino] = valor
        elif caja.codigo == "tiquipaya":
            destinos[destino] = _TIQ_DEFAULTS[destino]
        else:
            raise ValueError(
                f"DRIVE_AME_PENDIENTE: falta configurar {env_var} "
                f"(carpeta '{destino}' de CAJA AMERICA todavia no existe en Drive)."
            )
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

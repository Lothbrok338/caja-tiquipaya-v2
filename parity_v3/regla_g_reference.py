"""regla_g_reference.py — especificación ejecutable de REGLA G (búsqueda
EXACTA del cierre en Drive), FASE 4 de la estrategia de paridad V2 vs V3.

IMPORTANTE — esto NO es el código real de V2: la aplicación de REGLA G hoy
vive exclusivamente dentro de nodos n8n (Google Drive + IF) del workflow
`TIQ · PROCESAR CIERRES PENDIENTES · POC` (LkS0RHu9KEbHCR4p), no en Python.
La auditoría (auditoria_v2/V2_BUSINESS_RULES.csv, BR-008) ya señaló que el
parámetro exacto de cada nodo Google Drive no fue releído línea por línea, y
que no existe ningún test automatizado de esta regla (auditoria_v2/
V2_TEST_AUDIT.csv, T-021).

Esta función es, por lo tanto, la PRIMERA especificación ejecutable de la
regla, escrita a partir de:
  - el enunciado de la REGLA G tal como fue definido en la sesión de
    auditoría (incidente real: buscar "09" entre ["09","10","11"]);
  - el comportamiento observado en el workflow n8n vigente (nodos IF
    inmediatamente después de cada BUSCAR, y los códigos de estado
    CIERRE_NO_LOCALIZADO_EN_00_ENTRADA / CIERRE_AMBIGUO_EN_00_ENTRADA
    encontrados literalmente en snapshots/v2-final/n8n_workflow_active.json).

Sirve como CONTRATO ejecutable: tanto la implementación real de V2 (n8n) como
cualquier implementación futura de V3 (Python o n8n) deben producir,
para el mismo conjunto de nombres candidatos y el mismo nombre buscado,
exactamente el mismo veredicto que esta función.
"""

ENCONTRADO = "ENCONTRADO"
NO_LOCALIZADO = "CIERRE_NO_LOCALIZADO_EN_00_ENTRADA"
AMBIGUO = "CIERRE_AMBIGUO_EN_00_ENTRADA"


def buscar_cierre_exacto(nombre_buscado, nombres_en_carpeta):
    """Aplica REGLA G: coincidencia EXACTA de nombre de archivo, nunca
    'primer resultado'.

    - 1 coincidencia exacta -> (ENCONTRADO, ese nombre)
    - 0 coincidencias exactas -> (NO_LOCALIZADO, None)
    - >1 coincidencias exactas -> (AMBIGUO, None)

    'Coincidencia exacta' es comparación de string completo, no substring
    ni prefijo: "CIERRE 09-09-2026.xlsm" NUNCA hace match con
    "CIERRE 09-09-2026 (1).xlsm" ni con una búsqueda parcial "09".
    """
    exactas = [n for n in nombres_en_carpeta if n == nombre_buscado]
    if len(exactas) == 1:
        return ENCONTRADO, exactas[0]
    if len(exactas) == 0:
        return NO_LOCALIZADO, None
    return AMBIGUO, None

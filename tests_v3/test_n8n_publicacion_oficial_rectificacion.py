"""tests_v3/test_n8n_publicacion_oficial_rectificacion.py — BLOQUE 2.

Pruebas estructurales (grafo del workflow, no ejecucion real de n8n/Drive)
sobre snapshots/v3-final/wcgxNei3duWfMDp1_06b_publicacion_oficial.json:
confirman que RECTIFICAR CIERRE PUBLICADO reemplazo al placeholder
RECTIFICACION_NO_IMPLEMENTADA_06B, que el marker nuevo sigue siendo el
ultimo nodo de la cadena (PASO E), y que el camino PUBLICAR normal
(SAME SHA / SAME DATE+DIFERENTE SHA) no cambio respecto al BLOQUE 1.

La logica de las funciones de validacion/resolucion (fail-closed,
idempotencia, marker anterior) se prueba con fixtures sinteticas en
tests_v3/n8n_publicacion_oficial/test_logic_reference.js (Node puro, sin
n8n ni Drive) -- ver ese archivo para los 25 casos del requerimiento que
son de logica pura. Aqui solo se verifica la FORMA del grafo.

Uso: python -m pytest tests_v3/test_n8n_publicacion_oficial_rectificacion.py -q
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(
    REPO_ROOT, "snapshots", "v3-final", "wcgxNei3duWfMDp1_06b_publicacion_oficial.json"
)


def _cargar_workflow():
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        return json.load(f)


def _nombres_nodos(wf):
    return {n["name"] for n in wf["nodes"]}


def _destinos_de(wf, nombre_nodo, salida=0):
    rama = wf["connections"][nombre_nodo]["main"][salida]
    return [edge["node"] for edge in rama]


NODOS_RECTIFICACION_NUEVOS = [
    "BUSCAR - Resultado anterior en carpeta oficial (rectificacion)",
    "BUSCAR - Cierre previo en 03_PROCESADOS (rectificacion)",
    "BUSCAR - Cierre nuevo en 00_ENTRADA_CIERRES (rectificacion)",
    "VALIDAR - Identidades previas unicas (rectificacion)",
    "LISTAR - Markers PROCESADO en carpeta marker (rectificacion)",
    "DESCARGAR - Contenido de markers candidatos (rectificacion)",
    "RESOLVER - Marker anterior unico (rectificacion)",
    "LEER - SAP oficial local (rectificacion)",
    "ACTUALIZAR - SAP anterior en Drive (rectificacion)",
    "LEER - Resultado oficial local (rectificacion)",
    "ACTUALIZAR - Resultado anterior en Drive (rectificacion)",
    "DESCARGAR - Cierre nuevo desde ENTRADA (rectificacion)",
    "ACTUALIZAR - Cierre previo en PROCESADOS (rectificacion)",
    "ELIMINAR - Cierre residual en 00_ENTRADA (rectificacion)",
    "ELIMINAR - Marker anterior (rectificacion)",
    "LEER - Marker oficial local (rectificacion)",
    "SUBIR - Marker nuevo a Drive (rectificacion, ultimo paso)",
    "CONSTRUIR - Salida RECTIFICADO_OFICIAL",
]


def test_placeholder_no_implementada_ya_no_existe():
    wf = _cargar_workflow()
    assert "CONSTRUIR - Salida RECTIFICACION_NO_IMPLEMENTADA" not in _nombres_nodos(wf)
    assert "CONSTRUIR - Salida RECTIFICACION_NO_IMPLEMENTADA" not in wf["connections"]


def test_los_18_nodos_nuevos_de_rectificacion_existen():
    wf = _cargar_workflow()
    nombres = _nombres_nodos(wf)
    faltantes = [n for n in NODOS_RECTIFICACION_NUEVOS if n not in nombres]
    assert not faltantes, f"nodos de rectificacion faltantes: {faltantes}"
    assert len(NODOS_RECTIFICACION_NUEVOS) == 18


def test_rama_sap_existe_mas_rectificacion_true_entra_a_la_cadena_real():
    wf = _cargar_workflow()
    destinos = _destinos_de(wf, "IF - Rectificacion solicitada (SAP existe)", salida=0)
    assert destinos == ["BUSCAR - Resultado anterior en carpeta oficial (rectificacion)"]


def test_rama_sap_existe_mas_rectificacion_false_no_cambio_bloque1():
    wf = _cargar_workflow()
    destinos = _destinos_de(wf, "IF - Rectificacion solicitada (SAP existe)", salida=1)
    assert destinos == ["CONSTRUIR - Salida REQUIERE_RECTIFICACION"]


def test_rama_sap_no_existe_no_cambio_bloque1():
    # PUBLICAR normal (SAP no existe) sigue exactamente igual: BLOQUE 2 no
    # toca esta rama en absoluto.
    wf = _cargar_workflow()
    destinos_true = _destinos_de(wf, "IF - Rectificacion solicitada (SAP no existe)", salida=0)
    destinos_false = _destinos_de(wf, "IF - Rectificacion solicitada (SAP no existe)", salida=1)
    assert destinos_true == ["CONSTRUIR - Salida RECTIFICACION_SIN_PUBLICACION_PREVIA"]
    assert destinos_false == ["LEER - SAP oficial local"]


def test_marker_nuevo_sigue_siendo_el_ultimo_paso_logico():
    wf = _cargar_workflow()
    # PASO E: subir el marker nuevo es el ultimo nodo de escritura antes de
    # construir la salida; nada de la validacion/resolucion ocurre despues.
    destino = _destinos_de(wf, "SUBIR - Marker nuevo a Drive (rectificacion, ultimo paso)")
    assert destino == ["CONSTRUIR - Salida RECTIFICADO_OFICIAL"]
    # El marker anterior se elimina ANTES de leer/subir el nuevo, nunca despues.
    destino_eliminar = _destinos_de(wf, "ELIMINAR - Marker anterior (rectificacion)")
    assert destino_eliminar == ["LEER - Marker oficial local (rectificacion)"]


def test_orden_de_reemplazo_sap_resultado_procesados_antes_del_marker():
    wf = _cargar_workflow()
    cadena_esperada = [
        "RESOLVER - Marker anterior unico (rectificacion)",
        "LEER - SAP oficial local (rectificacion)",
        "ACTUALIZAR - SAP anterior en Drive (rectificacion)",
        "LEER - Resultado oficial local (rectificacion)",
        "ACTUALIZAR - Resultado anterior en Drive (rectificacion)",
        "DESCARGAR - Cierre nuevo desde ENTRADA (rectificacion)",
        "ACTUALIZAR - Cierre previo en PROCESADOS (rectificacion)",
        "ELIMINAR - Cierre residual en 00_ENTRADA (rectificacion)",
        "ELIMINAR - Marker anterior (rectificacion)",
        "LEER - Marker oficial local (rectificacion)",
        "SUBIR - Marker nuevo a Drive (rectificacion, ultimo paso)",
        "CONSTRUIR - Salida RECTIFICADO_OFICIAL",
    ]
    for origen, destino in zip(cadena_esperada, cadena_esperada[1:]):
        assert _destinos_de(wf, origen) == [destino], f"{origen} -> {destino}"


def test_cierre_residual_se_elimina_solo_despues_de_actualizar_procesados():
    wf = _cargar_workflow()
    destino = _destinos_de(wf, "ACTUALIZAR - Cierre previo en PROCESADOS (rectificacion)")
    assert destino == ["ELIMINAR - Cierre residual en 00_ENTRADA (rectificacion)"]


def test_grafo_sin_referencias_colgantes():
    wf = _cargar_workflow()
    nombres = _nombres_nodos(wf)
    for origen, salida in wf["connections"].items():
        assert origen in nombres, f"conexion desde nodo inexistente: {origen}"
        for rama in salida["main"]:
            for edge in rama:
                assert edge["node"] in nombres, f"conexion hacia nodo inexistente: {edge['node']}"


def test_nodos_de_rectificacion_reutilizan_credencial_drive_existente():
    wf = _cargar_workflow()
    por_nombre = {n["name"]: n for n in wf["nodes"]}
    for nombre in NODOS_RECTIFICACION_NUEVOS:
        nodo = por_nombre[nombre]
        if nodo["type"] == "n8n-nodes-base.googleDrive":
            assert nodo["credentials"]["googleDriveOAuth2Api"]["id"] == "aoEcEAFQQ38XcwZg"


def test_actualizaciones_usan_el_patron_probado_de_07d_publicar_oficial():
    # Mismo patron: resource=file, operation=update, changeFileContent=true.
    wf = _cargar_workflow()
    por_nombre = {n["name"]: n for n in wf["nodes"]}
    for nombre in (
        "ACTUALIZAR - SAP anterior en Drive (rectificacion)",
        "ACTUALIZAR - Resultado anterior en Drive (rectificacion)",
        "ACTUALIZAR - Cierre previo en PROCESADOS (rectificacion)",
    ):
        params = por_nombre[nombre]["parameters"]
        assert params["resource"] == "file"
        assert params["operation"] == "update"
        assert params["changeFileContent"] is True
        assert params["fileId"]["mode"] == "id"

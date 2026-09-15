"""tests_v3/test_drive_readonly_safety.py — FASE 10A: verifica que NINGUN
nodo Google Drive agregado a los subworkflows V3 (01 INGESTA, 02
MATERIALIZACION) sea capaz de escribir en Drive real. Lee directamente los
JSON exportados en snapshots/v3-dev-integrated/ (la definicion real de los
workflows en n8n, no una reinterpretacion) y falla si aparece cualquier
operacion de escritura (move/update/delete/upload/create) en un nodo
n8n-nodes-base.googleDrive.

Uso: python -m pytest tests_v3/test_drive_readonly_safety.py -q
"""

import json
import os

_AQUI = os.path.dirname(os.path.abspath(__file__))
_SNAPSHOTS_DIR = os.path.join(os.path.dirname(_AQUI), "snapshots", "v3-dev-integrated")

_ARCHIVOS_CON_DRIVE_REAL = [
    "CanZtkmnm0ukAC8c_01_ingesta.json",
    "j88aiRsPF7g9kxhD_02_materializacion.json",
]

# Unicas operaciones de Google Drive permitidas en el camino drive_readonly:
# buscar/listar (resource=fileFolder, operation=search) y descargar
# (resource=file, operation=download). Cualquier otra cosa (move, update,
# delete_file, upload, create_from_text, share, copy, create/delete de
# folder o de drive) implica escritura o modificacion en Drive real y NUNCA
# debe aparecer en estos subworkflows.
_OPERACIONES_PERMITIDAS = {("fileFolder", "search"), ("file", "download")}


def _cargar_nodos_google_drive(nombre_archivo):
    ruta = os.path.join(_SNAPSHOTS_DIR, nombre_archivo)
    with open(ruta, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    return [n for n in workflow["nodes"] if n.get("type") == "n8n-nodes-base.googleDrive"]


def test_snapshots_existen_y_tienen_al_menos_un_nodo_drive():
    for nombre in _ARCHIVOS_CON_DRIVE_REAL:
        nodos = _cargar_nodos_google_drive(nombre)
        assert len(nodos) >= 1, f"{nombre}: se esperaba al menos un nodo googleDrive real"


def test_ningun_nodo_google_drive_usa_una_operacion_de_escritura():
    for nombre in _ARCHIVOS_CON_DRIVE_REAL:
        for nodo in _cargar_nodos_google_drive(nombre):
            resource = nodo["parameters"].get("resource")
            operation = nodo["parameters"].get("operation")
            par = (resource, operation)
            assert par in _OPERACIONES_PERMITIDAS, (
                f"{nombre}: nodo '{nodo['name']}' usa resource={resource!r} "
                f"operation={operation!r}, fuera de las operaciones de SOLO "
                f"LECTURA permitidas {_OPERACIONES_PERMITIDAS}"
            )


def test_ningun_nodo_google_drive_tiene_operacion_explicitamente_prohibida():
    prohibidas = {"move", "update", "delete_file", "delete_folder", "delete_drive",
                  "upload", "create_from_text", "create", "share", "copy"}
    for nombre in _ARCHIVOS_CON_DRIVE_REAL:
        for nodo in _cargar_nodos_google_drive(nombre):
            operation = nodo["parameters"].get("operation")
            assert operation not in prohibidas, (
                f"{nombre}: nodo '{nodo['name']}' usa una operacion de escritura prohibida: {operation!r}"
            )


def test_busqueda_de_entrada_no_filtra_por_nombre_trae_listado_completo():
    # CONTRACT-010 / incidente 09-10-11: la busqueda de la carpeta de
    # entrada NUNCA debe filtrar por nombre en Drive (eso reintroduciria la
    # dependencia de un query fuzzy) -- REGLA G decide en Python sobre el
    # listado COMPLETO.
    nodos = _cargar_nodos_google_drive("CanZtkmnm0ukAC8c_01_ingesta.json")
    listado = next(n for n in nodos if n["name"] == "BUSCAR - Listado real 00_ENTRADA_CIERRES (solo lectura)")
    assert listado["parameters"].get("queryString") == ""
    assert listado["parameters"]["filter"]["whatToSearch"] == "files"
    assert listado["parameters"]["filter"]["includeTrashed"] is False


def test_credenciales_expuestas_son_solo_referencia_sin_secreto():
    # Un nodo googleDrive solo puede llevar {id, name} de la credencial
    # (referencia interna de n8n) -- nunca un campo con el secreto/token en
    # si (n8n no lo devuelve via API de todos modos, pero esto documenta la
    # expectativa explicita del encargo: "no exportar ni mostrar secretos").
    campos_permitidos = {"id", "name"}
    for nombre in _ARCHIVOS_CON_DRIVE_REAL:
        for nodo in _cargar_nodos_google_drive(nombre):
            cred = nodo.get("credentials", {}).get("googleDriveOAuth2Api", {})
            assert set(cred.keys()) <= campos_permitidos, (
                f"{nombre}: nodo '{nodo['name']}' expone campos de credencial inesperados: {cred.keys()}"
            )

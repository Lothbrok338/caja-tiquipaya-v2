"""tests_v3/test_adapt_workflows_railway.py — migración Railway 2026-09.

Valida el generador scripts/adapt_workflows_for_railway.py y los
artefactos de portabilidad que produce/requiere: 0 process.env restantes
en Code nodes, las 57 sustituciones $env.TIQ_BASE_DIR/TIQ_PLANTILLA_SAP_MAESTRA esperadas,
invariante de IDs de nodo (nada desaparece; solo aparecen las 3 guardas
SHADOW deliberadas), idempotencia del generador, y que la plantilla SAP
maestra versionada como asset es real y válida.

No requiere Drive, n8n ni Railway: todo es lectura de archivos locales
del repo y ejecución del generador sobre snapshots/v3-final/.

Uso: python -m pytest tests_v3/test_adapt_workflows_railway.py -q
"""
import json
import os
import subprocess
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

DST_DIR = os.path.join(RAIZ, "snapshots", "railway-shadow")
GENERADOR = os.path.join(RAIZ, "scripts", "adapt_workflows_for_railway.py")

BACKEND = "aLs1f3GMqswbaENA_backend_dev.json"
INGESTA = "CanZtkmnm0ukAC8c_01_ingesta.json"
GUARDAS_ESPERADAS = {
    "wcgxNei3duWfMDp1_06b_publicacion_oficial.json": "a1a1a1a1-0001-4a1a-9a1a-000000000001",
    "HhuQCVP2oCubavzY_07d_publicar_oficial.json": "a1a1a1a1-0002-4a1a-9a1a-000000000002",
    "Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json": "a1a1a1a1-0003-4a1a-9a1a-000000000003",
}
NOMBRE_GUARDIA = "GUARDIA SHADOW (bloquea si TIQ_BLOCK_OFFICIAL_PUBLISH)"


def _contar(patron, archivos):
    """(nº de nodos con al menos 1 ocurrencia, total de ocurrencias) de
    `patron` dentro de los campos jsCode/command de todos los nodos de
    los `archivos` dados (rutas absolutas)."""
    total_nodos, total_occ = 0, 0
    for ruta in archivos:
        wf = json.load(open(ruta, encoding="utf-8"))
        for nodo in wf.get("nodes", []):
            params = nodo.get("parameters", {})
            for key in ("jsCode", "command"):
                val = params.get(key)
                if isinstance(val, str) and patron in val:
                    total_nodos += 1
                    total_occ += val.count(patron)
    return total_nodos, total_occ


@pytest.fixture(scope="module", autouse=True)
def _regenerar():
    """Regenera snapshots/railway-shadow/ una vez para todo el módulo,
    desde el generador real — nunca se edita a mano lo que este test lee."""
    r = subprocess.run([sys.executable, GENERADOR], cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0, f"adapt_workflows_for_railway.py falló:\n{r.stdout}\n{r.stderr}"
    yield


def test_cero_process_env_en_code_nodes():
    archivos = [os.path.join(DST_DIR, BACKEND), os.path.join(DST_DIR, INGESTA)]
    nodos, occ = _contar("process.env", archivos)
    assert (nodos, occ) == (0, 0), "no debe quedar ningún process.env en los Code nodes adaptados"


def test_57_sustituciones_de_process_env_quedan_contabilizadas():
    """El inventario auditado (18 Code nodes, 57 ocurrencias de
    process.env) se reparte ahora en dos variables: 54 en
    $env.TIQ_BASE_DIR (la ruta base genérica) y 3 en
    $env.TIQ_PLANTILLA_SAP_MAESTRA (la ruta específica de la plantilla,
    ver test_ruta_plantilla_origen_en_backend_apunta_al_asset_versionado)
    — las 3 que antes también caían dentro de esas 57 porque el literal
    de la plantilla contenía el mismo prefijo /home/codespace/.n8n-files.
    El total sigue siendo 57: ninguna ocurrencia se pierde. (Antes del
    webhook /global-institucional -- nodo 'CONSTRUIR payload global
    institucional' -- el inventario era 17/53: ese nodo nuevo aporta 3
    ocurrencias de TIQ_BASE_DIR y 1 de TIQ_PLANTILLA_SAP_MAESTRA.)"""
    archivos = [os.path.join(DST_DIR, BACKEND), os.path.join(DST_DIR, INGESTA)]
    nodos_base, occ_base = _contar("$env.TIQ_BASE_DIR", archivos)
    _, occ_plantilla = _contar("$env.TIQ_PLANTILLA_SAP_MAESTRA", archivos)
    assert nodos_base == 18
    assert occ_base == 54
    assert occ_plantilla == 3
    assert occ_base + occ_plantilla == 57


def test_env_tiq_base_dir_solo_en_code_nodes_no_en_execute_command():
    wf = json.load(open(os.path.join(DST_DIR, BACKEND), encoding="utf-8"))
    for nodo in wf["nodes"]:
        if nodo["type"] == "n8n-nodes-base.executeCommand":
            comando = nodo["parameters"].get("command", "")
            assert "$env.TIQ_BASE_DIR" not in comando
            # Los Execute Command siguen usando su propio patrón, sin tocar.
            if "TIQ_REPO_ROOT" in comando or "TIQ_PYTHON_BIN" in comando:
                assert "{{ $env.TIQ_REPO_ROOT" in comando
                assert "{{ $env.TIQ_PYTHON_BIN" in comando


def test_idempotente_dos_corridas_producen_bytes_identicos():
    antes = {}
    for nombre in os.listdir(DST_DIR):
        with open(os.path.join(DST_DIR, nombre), "rb") as f:
            antes[nombre] = f.read()
    r = subprocess.run([sys.executable, GENERADOR], cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0
    for nombre, contenido in antes.items():
        with open(os.path.join(DST_DIR, nombre), "rb") as f:
            assert f.read() == contenido, f"{nombre}: el generador no es idempotente"


def test_ids_de_nodo_no_desaparecen_y_solo_se_agregan_las_guardas_deliberadas():
    for nombre_dst, guard_id in GUARDAS_ESPERADAS.items():
        original = json.load(open(os.path.join(RAIZ, "snapshots", "v3-final", nombre_dst), encoding="utf-8"))
        adaptado = json.load(open(os.path.join(DST_DIR, nombre_dst), encoding="utf-8"))
        ids_antes = {n["id"] for n in original["nodes"]}
        ids_despues = {n["id"] for n in adaptado["nodes"]}
        assert ids_antes <= ids_despues, f"{nombre_dst}: desapareció un nodo original"
        assert ids_despues - ids_antes == {guard_id}, f"{nombre_dst}: nodos agregados inesperados"

    # BACKEND y 01 INGESTA: solo se parchea jsCode, ningún nodo nuevo.
    for nombre_dst in (BACKEND, INGESTA):
        original = json.load(open(os.path.join(RAIZ, "snapshots", "v3-final", nombre_dst), encoding="utf-8"))
        adaptado = json.load(open(os.path.join(DST_DIR, nombre_dst), encoding="utf-8"))
        assert {n["id"] for n in original["nodes"]} == {n["id"] for n in adaptado["nodes"]}


def test_guardas_shadow_presentes_y_cableadas_antes_del_primer_nodo():
    destinos_originales = {
        "wcgxNei3duWfMDp1_06b_publicacion_oficial.json": "RESOLVER - Destinos Drive por caja",
        "HhuQCVP2oCubavzY_07d_publicar_oficial.json": "BUSCAR - Archivo por nombre en carpeta",
        "Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json": "BUSCAR - Subcarpeta por nombre",
    }
    for nombre_dst, destino in destinos_originales.items():
        wf = json.load(open(os.path.join(DST_DIR, nombre_dst), encoding="utf-8"))
        nombres_nodos = {n["name"] for n in wf["nodes"]}
        assert NOMBRE_GUARDIA in nombres_nodos
        trigger_conn = wf["connections"]["ENTRADA (Execute Workflow Trigger)"]
        assert trigger_conn["main"][0][0]["node"] == NOMBRE_GUARDIA
        assert wf["connections"][NOMBRE_GUARDIA]["main"][0][0]["node"] == destino

    # 06B: la guardia debe seguir precediendo a RESOLVER, que a su vez
    # sigue enrutando hacia BUSCAR - Marker existente en Drive, sin saltarse
    # el nodo de resolución de destinos añadido después de la guardia SHADOW.
    wf_06b = json.load(
        open(os.path.join(DST_DIR, "wcgxNei3duWfMDp1_06b_publicacion_oficial.json"), encoding="utf-8")
    )
    assert (
        wf_06b["connections"]["RESOLVER - Destinos Drive por caja"]["main"][0][0]["node"]
        == "BUSCAR - Marker existente en Drive"
    )


def test_plantilla_sap_maestra_runtime_existe_y_es_valida():
    ruta = os.path.join(RAIZ, "assets", "Plantilla SAP maestra.xlsx")
    assert os.path.isfile(ruta), "assets/Plantilla SAP maestra.xlsx debe existir versionada en el repo"
    import hashlib
    with open(ruta, "rb") as f:
        contenido = f.read()
    assert hashlib.sha256(contenido).hexdigest() == "17b27d79d103fbb87926ae18578f2724e369792e8cfeec4b5456990cb7008e43"

    import openpyxl
    wb = openpyxl.load_workbook(ruta, data_only=True)
    assert "1" in wb.sheetnames, "la hoja que el motor espera ('1') debe existir"


def test_ruta_plantilla_origen_en_backend_apunta_al_asset_versionado():
    wf = json.load(open(os.path.join(DST_DIR, BACKEND), encoding="utf-8"))
    nodo = next(n for n in wf["nodes"] if n["name"] == "CONSTRUIR payload procesar_lote")
    codigo = nodo["parameters"]["jsCode"]
    assert "$env.TIQ_PLANTILLA_SAP_MAESTRA" in codigo
    assert "/app/assets/Plantilla SAP maestra.xlsx" in codigo


def test_n8n_restrict_file_access_incluye_tiq_base_dir():
    ruta = os.path.join(RAIZ, "scripts", "start_n8n.sh")
    contenido = open(ruta, encoding="utf-8").read()
    assert "N8N_RESTRICT_FILE_ACCESS_TO=" in contenido
    linea = next(l for l in contenido.splitlines() if l.strip().startswith("export N8N_RESTRICT_FILE_ACCESS_TO="))
    assert "TIQ_BASE_DIR" in linea
    assert linea.strip() != 'export N8N_RESTRICT_FILE_ACCESS_TO="/"', "nunca abrir todo el filesystem"


def test_dockerfile_fija_version_n8n():
    contenido = open(os.path.join(RAIZ, "Dockerfile"), encoding="utf-8").read()
    assert "npm install -g n8n@2.35.7" in contenido
    assert "npm install -g n8n\n" not in contenido, "no debe quedar una instalación de n8n sin version fijada"

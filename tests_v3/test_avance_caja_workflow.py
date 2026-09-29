"""tests_v3/test_avance_caja_workflow.py — workflow n8n "AVANCE CAJA" (solo lectura).

Valida, sin n8n ni Drive reales, el snapshot
snapshots/railway-shadow/AvncCajaRO7v3Dev_avance_caja.json que expone
GET /webhook/tiq-v3-dev/avance:

  - estructura válida (ids/nombres únicos, conexiones a nodos existentes);
  - SOLO LECTURA: el único nodo Drive es un `search`, sin escritura ni borrado
    ni movimiento, y el único Execute Command que corre Python invoca
    exclusivamente la acción `avance_caja`;
  - la tabla por caja del nodo RESOLVER coincide con config_cajas.py y
    config_drive_oficial.py (misma variable DRIVE_SAP_<prefijo>, mismo default
    histórico solo para TIQUIPAYA, AMERICA sin default y fail-closed): sumar una
    caja en Python sin su fila en n8n rompe este test.

El nodo RESOLVER se ejecuta con el `node` real (stubs de `$`/`$env`).

Uso: python -m pytest tests_v3/test_avance_caja_workflow.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import config_cajas as cfg  # noqa: E402
import config_drive_oficial as drive_cfg  # noqa: E402

RUTA = os.path.join(RAIZ, "snapshots", "railway-shadow", "AvncCajaRO7v3Dev_avance_caja.json")
wf = json.load(open(RUTA, encoding="utf-8"))
NODOS = {n["name"]: n for n in wf["nodes"]}


def test_estructura_valida():
    assert len(NODOS) == len(wf["nodes"]), "nombres de nodo repetidos"
    assert len({n["id"] for n in wf["nodes"]}) == len(wf["nodes"]), "ids de nodo repetidos"
    for origen, salidas in wf["connections"].items():
        assert origen in NODOS
        for rama in salidas["main"]:
            for destino in rama:
                assert destino["node"] in NODOS, f"{origen} -> {destino['node']} inexistente"
    assert wf["id"] and len(wf["id"]) == 16
    assert wf["settings"]["executionOrder"] == "v1"


def test_un_solo_webhook_get_y_todas_las_ramas_responden():
    webhooks = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
    assert len(webhooks) == 1
    assert webhooks[0]["parameters"]["httpMethod"] == "GET"
    assert webhooks[0]["parameters"]["path"] == "tiq-v3-dev/avance"
    assert webhooks[0]["parameters"]["responseMode"] == "responseNode"
    # Toda rama termina en un respondToWebhook (nunca un cliente colgado).
    responders = {n["name"] for n in wf["nodes"] if n["type"] == "n8n-nodes-base.respondToWebhook"}
    sin_salida = {n for n in NODOS if n not in wf["connections"]}
    assert sin_salida == responders


def test_el_path_no_choca_con_los_webhooks_existentes():
    backend = json.load(open(os.path.join(RAIZ, "snapshots", "railway-shadow", "aLs1f3GMqswbaENA_backend_dev.json"), encoding="utf-8"))
    existentes = {n["parameters"].get("path") for n in backend["nodes"] if n["type"] == "n8n-nodes-base.webhook"}
    assert "tiq-v3-dev/avance" not in existentes


def test_solo_lectura_en_drive():
    drive = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.googleDrive"]
    assert len(drive) == 1
    p = drive[0]["parameters"]
    assert (p["resource"], p["operation"]) == ("fileFolder", "search")
    assert set(drive[0]["credentials"]) == {"googleDriveOAuth2Api"}
    assert p["filter"]["includeTrashed"] is False


def test_unico_python_es_avance_caja_y_nada_mas_ejecuta_comandos():
    comandos = [n["parameters"]["command"] for n in wf["nodes"] if n["type"] == "n8n-nodes-base.executeCommand"]
    assert len(comandos) == 2
    python = [c for c in comandos if "v3.dev_api" in c]
    assert len(python) == 1 and "--accion avance_caja" in python[0]
    escritura = [c for c in comandos if "v3.dev_api" not in c][0]
    assert escritura.startswith("=printf '%s'") and "base64 -d >" in escritura and "tiq_v3" not in escritura  # solo el input tmp


def test_no_toca_motor_publicacion_ni_marcadores():
    texto = json.dumps(wf)
    for prohibido in ("publicar", "procesar_lote", "PROCESADO_", "upload", "deleteFile", "move", "update"):
        assert prohibido not in texto, prohibido


NODE = shutil.which("node")


def _resolver(caja, entorno):
    js = NODOS["RESOLVER - Carpeta SAP de la caja"]["parameters"]["jsCode"]
    harness = (
        "const $env = JSON.parse(process.argv[2]);"
        "const query = { caja: process.argv[1] };"
        "const $ = () => ({ first: () => ({ json: { query: query } }) });"
        "const salida = (function () {" + js + "})();"
        "console.log(JSON.stringify(salida[0].json));"
    )
    r = subprocess.run([NODE, "-e", harness, caja, json.dumps(entorno)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="node no disponible")
def test_tabla_por_caja_coincide_con_la_configuracion_de_python():
    for codigo, caja in cfg.CAJAS.items():
        variable = drive_cfg.nombre_variable_entorno(codigo, "sap")
        assert variable == f"DRIVE_SAP_{caja.prefijo_archivo}"
        # con la variable definida: usa esa carpeta
        r = _resolver(codigo, {variable: "carpeta-env"})
        assert r == {"caja": codigo, "folder_sap_id": "carpeta-env", "motivo": None}
        # sin variable: TIQUIPAYA -> default histórico; el resto falla cerrado (nunca el folder de TIQ)
        r = _resolver(codigo, {})
        try:
            esperado = drive_cfg.resolver_destinos_drive(codigo, entorno={})["sap"]
        except ValueError:
            assert r["folder_sap_id"] is None and r["motivo"] == variable + "_NO_CONFIGURADA"
        else:
            assert r["folder_sap_id"] == esperado and r["motivo"] is None


@pytest.mark.skipif(NODE is None, reason="node no disponible")
def test_caja_desconocida_o_ausente():
    assert _resolver("inexistente", {}) == {"caja": "inexistente", "folder_sap_id": None, "motivo": "CAJA_DESCONOCIDA"}
    assert _resolver("", {})["caja"] == "tiquipaya"  # default absoluto del sistema
    assert _resolver("AMERICA", {"DRIVE_SAP_AME": "x"})["caja"] == "america"

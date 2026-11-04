"""tests_v3/test_n8n_global_paired_item.py — GENERAR GLOBAL fallaba con
"Paired item data for item from node 'FILTRAR - SAP diarios validos del
periodo' is unavailable" (hallazgo real, Tiquipaya, octubre 2026).

Causa (motor de expresiones de n8n 2.35.x, workflow-data-proxy): `$('X').item`
resuelve el item "pareado" caminando hacia atras por `pairedItem` de cada nodo.
FILTRAR es un Code que recibe M archivos de la carpeta SAP de Drive y devuelve N
validos del periodo/caja: si M != N (y N != 1) n8n NO puede asignarle pairedItem,
y cualquier `$('X').item` evaluado aguas abajo con X aguas ARRIBA de FILTRAR
falla. Antes funcionaba solo porque la carpeta traia exactamente los N archivos
validos (M == N). El unico caso real era DECIDIR - Publicar GLOBAL oficial, que
leia `$('WEBHOOK global').item`; el webhook tiene siempre UN item, asi que
`.first()` es equivalente y no depende del pareo.

Estas pruebas son estaticas (sin n8n): cuidan que ningun nodo aguas abajo de
FILTRAR dependa del pareo de un nodo aguas arriba.

Uso: python -m pytest tests_v3/test_n8n_global_paired_item.py -q
"""
import json
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = "aLs1f3GMqswbaENA_backend_dev.json"
SNAPSHOTS = ("v3-final", "railway-shadow")
FILTRAR = "FILTRAR - SAP diarios validos del periodo"
DECIDIR = "DECIDIR - Publicar GLOBAL oficial"

# Referencias que dependen del pareo de items: $('X').item / .itemMatching( / .pairedItem
# y la sintaxis antigua $node["X"] (que tambien resuelve por pareo).
_RE_PAREADAS = re.compile(
    r"""\$\(\s*['"]([^'"]+)['"]\s*\)\s*\.\s*(?:item\b|itemMatching\s*\(|pairedItem\b)"""
    r"""|\$node\[\s*['"]([^'"]+)['"]\s*\]"""
)


def _cargar(snapshot):
    ruta = os.path.join(RAIZ, "snapshots", snapshot, BACKEND)
    with open(ruta, encoding="utf-8") as f:
        wf = json.load(f)
    return {n["name"]: n for n in wf["nodes"]}, wf["connections"]


def _descendientes(conexiones, origen):
    vistos, cola = set(), [origen]
    while cola:
        actual = cola.pop(0)
        for rama in conexiones.get(actual, {}).get("main", []):
            for enlace in rama or []:
                if enlace["node"] not in vistos:
                    vistos.add(enlace["node"])
                    cola.append(enlace["node"])
    return vistos


def referencias_pareadas_hacia_arriba(nodos, conexiones):
    """[(nodo, objetivo)] de los nodos aguas abajo de FILTRAR que usan pareo contra un
    nodo que NO esta aguas abajo de FILTRAR (n8n no puede cruzar FILTRAR cuando M != N)."""
    abajo = _descendientes(conexiones, FILTRAR)
    malas = []
    for nombre in sorted(abajo):
        texto = json.dumps(nodos[nombre].get("parameters", {}), ensure_ascii=False)
        for m in _RE_PAREADAS.finditer(texto):
            objetivo = m.group(1) or m.group(2)
            if objetivo not in abajo:
                malas.append((nombre, objetivo))
    return sorted(set(malas))


@pytest.mark.parametrize("snapshot", SNAPSHOTS)
def test_ningun_nodo_aguas_abajo_de_filtrar_depende_del_pareo_de_un_nodo_aguas_arriba(snapshot):
    nodos, conexiones = _cargar(snapshot)
    assert FILTRAR in nodos
    assert referencias_pareadas_hacia_arriba(nodos, conexiones) == []


@pytest.mark.parametrize("snapshot", SNAPSHOTS)
def test_decidir_publicar_global_lee_el_webhook_con_first_y_no_con_item(snapshot):
    nodos, _ = _cargar(snapshot)
    codigo = nodos[DECIDIR]["parameters"]["jsCode"]
    assert "$('WEBHOOK global').first().json.body" in codigo
    assert "$('WEBHOOK global').item" not in codigo


def test_el_detector_encuentra_la_referencia_que_rompia_global():
    """Sanidad del detector: con el codigo anterior de DECIDIR si marca el problema."""
    nodos, conexiones = _cargar("railway-shadow")
    roto = json.loads(json.dumps(nodos))
    roto[DECIDIR]["parameters"]["jsCode"] = roto[DECIDIR]["parameters"]["jsCode"].replace(
        "$('WEBHOOK global').first()", "$('WEBHOOK global').item")
    assert referencias_pareadas_hacia_arriba(roto, conexiones) == [(DECIDIR, "WEBHOOK global")]

#!/usr/bin/env python3
"""scripts/adapt_workflows_for_railway.py — genera copias portables de los
workflows n8n activos para el entorno sombra Railway (cajas-gabo-shadow).

Por qué existe: los 2 workflows n8n activos que invocan Python (BACKEND DEV
`aLs1f3GMqswbaENA` y 01 INGESTA `CanZtkmnm0ukAC8c`) tienen, en sus nodos
Execute Command, rutas absolutas hardcodeadas del Codespace real:
  - `/workspaces/caja-tiquipaya-v2` (raíz del repo)
  - `/workspaces/.venv-caja/bin/python3` (intérprete)
  - `/home/codespace/.n8n-files/...` (directorio base de trabajo de n8n)
Ningún flujo de trabajo se reescribe: solo se sustituyen estos 3 literales
por expresiones n8n / JS con fallback exacto al valor original, así que
sin las variables de entorno nuevas (TIQ_REPO_ROOT, TIQ_PYTHON_BIN,
TIQ_BASE_DIR) el comportamiento es IDÉNTICO al snapshot original — esto
es estrictamente portabilidad, no un cambio de lógica ni de reglas
contables. Ver V3_OPEN_MONTH_STATE.md y snapshots/v3-final/SNAPSHOT_MANIFEST.md.

Este script NUNCA toca snapshots/v3-final/ (fuente de verdad / backup de
lo que corre hoy en Codespaces): lee de ahí y escribe copias adaptadas en
snapshots/railway-shadow/. Los otros 5 workflows activos (06B, PREFLIGHT,
07C, 07D, 07E) no tienen estos literales (verificado por grep) y se
copian tal cual, sin modificar, para tener el set completo de 7 en un
solo lugar listo para importar.

Uso: python3 scripts/adapt_workflows_for_railway.py
"""
import json
import os
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "snapshots", "v3-final")
DST_DIR = os.path.join(REPO_ROOT, "snapshots", "railway-shadow")

# Los 7 workflows activos en Codespaces (ver V3_OPEN_MONTH_STATE.md §3).
ACTIVE_WORKFLOWS = [
    "aLs1f3GMqswbaENA_backend_dev.json",
    "CanZtkmnm0ukAC8c_01_ingesta.json",
    "wcgxNei3duWfMDp1_06b_publicacion_oficial.json",
    "sJVgoBRpBntc96vf_preflight_oficial.json",
    "fn7lLjHsiMd48DGK_07c_descargar_oficial.json",
    "HhuQCVP2oCubavzY_07d_publicar_oficial.json",
    "Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json",
]

REPLACEMENTS = [
    (
        "cd /workspaces/caja-tiquipaya-v2 && /workspaces/.venv-caja/bin/python3",
        "cd {{ $env.TIQ_REPO_ROOT || '/workspaces/caja-tiquipaya-v2' }} && "
        "{{ $env.TIQ_PYTHON_BIN || '/workspaces/.venv-caja/bin/python3' }}",
    ),
    (
        "/home/codespace/.n8n-files",
        "' + (process.env.TIQ_BASE_DIR || \\\"/home/codespace/.n8n-files\\\") + '",
    ),
]


def adaptar(texto):
    for antes, despues in REPLACEMENTS:
        texto = texto.replace(antes, despues)
    return texto


def main():
    os.makedirs(DST_DIR, exist_ok=True)
    reporte = []
    for nombre in ACTIVE_WORKFLOWS:
        src = os.path.join(SRC_DIR, nombre)
        dst = os.path.join(DST_DIR, nombre)
        with open(src, "r", encoding="utf-8") as f:
            original = f.read()

        # Valida que el original ya es JSON válido antes de tocarlo.
        original_obj = json.loads(original)
        adaptado = adaptar(original)
        adaptado_obj = json.loads(adaptado)  # debe seguir siendo JSON válido

        cambios = sum(original.count(a) for a, _ in REPLACEMENTS)
        # Invariante: la adaptación no cambia el número de nodos ni sus IDs.
        nodos_antes = {n["id"] for n in original_obj.get("nodes", [])}
        nodos_despues = {n["id"] for n in adaptado_obj.get("nodes", [])}
        assert nodos_antes == nodos_despues, f"{nombre}: IDs de nodos cambiaron"

        with open(dst, "w", encoding="utf-8") as f:
            f.write(adaptado)
        reporte.append((nombre, cambios, len(nodos_despues)))

    print(f"Copiado/adaptado en {DST_DIR}:")
    for nombre, cambios, n_nodos in reporte:
        estado = f"{cambios} literales sustituidos" if cambios else "sin cambios (copia tal cual)"
        print(f"  - {nombre}: {estado}, {n_nodos} nodos")

    manifest_src = os.path.join(SRC_DIR, "SNAPSHOT_MANIFEST.md")
    if os.path.isfile(manifest_src):
        shutil.copyfile(manifest_src, os.path.join(DST_DIR, "SOURCE_SNAPSHOT_MANIFEST.md"))


if __name__ == "__main__":
    main()

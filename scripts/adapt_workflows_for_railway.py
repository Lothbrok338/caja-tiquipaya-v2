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

# Se aplica ANTES que REPLACEMENTS, con un token único de por medio: esta
# ruta contiene la misma "/home/codespace/.n8n-files" que sustituye la
# regla genérica de abajo, así que si se sustituyera después terminaría
# doblemente envuelta. El placeholder no contiene ese literal, así que la
# regla genérica lo ignora sin tocarlo.
_PLANTILLA_PLACEHOLDER = "@@TIQ_PLANTILLA_SAP_MAESTRA_PLACEHOLDER@@"
PRE_REPLACEMENTS = [
    (
        "/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/plantilla_origen/Plantilla SAP maestra.xlsx",
        _PLANTILLA_PLACEHOLDER,
    ),
]

REPLACEMENTS = [
    (
        "cd /workspaces/caja-tiquipaya-v2 && /workspaces/.venv-caja/bin/python3",
        "cd {{ $env.TIQ_REPO_ROOT || '/workspaces/caja-tiquipaya-v2' }} && "
        "{{ $env.TIQ_PYTHON_BIN || '/workspaces/.venv-caja/bin/python3' }}",
    ),
    # $env, NO process.env: esta sustitución cae dentro del cuerpo JS de
    # nodos Code (n8n-nodes-base.code), no de un parámetro de expresión
    # {{ }} — ahí `$env` es el binding nativo que n8n expone dentro del
    # propio código (mismo objeto que en las expresiones {{ $env.X }} de
    # los Execute Command de arriba). `process.env` funcionaba en el motor
    # de Code nodes "antiguo" (vm2, en proceso), pero n8n 2.x ejecuta los
    # Code nodes en un Task Runner externo que no expone `process` en el
    # sandbox — con TIQ_BASE_DIR sin poder leerse nunca, el fallback
    # hardcodeado a Codespaces queda activo siempre y en silencio, sin
    # error visible. `$env` sí está disponible en ambos modos.
    (
        "/home/codespace/.n8n-files",
        "' + ($env.TIQ_BASE_DIR || \\\"/home/codespace/.n8n-files\\\") + '",
    ),
]

# Se aplica DESPUÉS de REPLACEMENTS: convierte el placeholder en la
# expresión final. Default = el asset versionado en el repo
# (assets/Plantilla SAP maestra.xlsx, ver Dockerfile: COPY . . lo deja en
# /app/assets/), no la ruta efímera de Codespaces — a diferencia de
# TIQ_BASE_DIR/TIQ_REPO_ROOT/TIQ_PYTHON_BIN, esta ruta nunca tuvo un
# equivalente funcional en Railway (dev_workdir es efímero, sin volumen),
# así que no hay comportamiento previo de Railway que preservar por
# defecto. El motor SIEMPRE copia la plantilla antes de escribirla
# (ver v3/materializacion.py), así que el asset original queda intacto.
POST_REPLACEMENTS = [
    (
        _PLANTILLA_PLACEHOLDER,
        "' + ($env.TIQ_PLANTILLA_SAP_MAESTRA || \\\"/app/assets/Plantilla SAP maestra.xlsx\\\") + '",
    ),
]


def adaptar(texto):
    for antes, despues in PRE_REPLACEMENTS:
        texto = texto.replace(antes, despues)
    for antes, despues in REPLACEMENTS:
        texto = texto.replace(antes, despues)
    for antes, despues in POST_REPLACEMENTS:
        texto = texto.replace(antes, despues)
    return texto


# ---------------------------------------------------------------------------
# SHADOW — hardening a nivel de objeto (no de texto): BACKEND deja de
# declarar publicación oficial cuando TIQ_BLOCK_OFFICIAL_PUBLISH está
# activo (defensa en profundidad, además de la que ya existe en
# v3/shadow_guard.py). Se aplica DESPUÉS de adaptar() sobre el objeto ya
# parseado, con find/replace acotados al jsCode de CADA nodo por nombre
# (nunca texto libre sobre el archivo completo) para no arriesgar un
# match accidental en otro nodo. Cada find se verifica: si no aparece
# exactamente una vez, el script falla en vez de aplicar un cambio a
# medias. Ningún cálculo contable se toca — solo estos 6 nodos de
# enrutamiento de publicación oficial.
# ---------------------------------------------------------------------------

_GUARD_JS_DECL = (
    "const guardActivo = ['true', '1', 'yes'].includes("
    "String($env.TIQ_BLOCK_OFFICIAL_PUBLISH || '').trim().toLowerCase());"
)

BACKEND_JSCODE_PATCHES = {
    "AGREGAR - publication_mode": [
        (
            "const original = $json.data || {};\n"
            "return [{ json: Object.assign({}, original, { publication_mode: 'official' }) }];",
            "// SHADOW (migracion Railway): con TIQ_BLOCK_OFFICIAL_PUBLISH activo el backend\n"
            "// nunca declara 'official', sin importar el wiring de /publicar de arriba.\n"
            "// Inactiva por defecto: mismo 'official' de siempre.\n"
            f"{_GUARD_JS_DECL}\n"
            "const original = $json.data || {};\n"
            "return [{ json: Object.assign({}, original, { publication_mode: guardActivo ? 'dev' : 'official' }) }];",
        ),
    ],
    "CONSTRUIR payload publicar": [
        (
            "const t = $input.first().json;",
            "const t = $input.first().json;\n"
            "// SHADOW (migracion Railway): modo_oficial se deriva del mismo guard que\n"
            "// publication_mode -- inactivo por defecto (mismo modo_oficial=true de siempre).\n"
            f"{_GUARD_JS_DECL}",
        ),
        (
            "modo_oficial: true };",
            "modo_oficial: !guardActivo };",
        ),
    ],
    "PREPARAR - Cierres elegibles para Drive oficial": [
        (
            "const data = $json.data || {};\n"
            "const publicados = data.publicados || [];\n"
            "const elegibles = publicados.filter(function(c){ return c && c.ruta_sap_publicado && c.ruta_resultado_publicado && c.ruta_marker && c.sha256; });\n"
            "return [{ json: { elegibles: elegibles, hay_elegibles: elegibles.length > 0 } }];",
            f"{_GUARD_JS_DECL}\n"
            "const data = $json.data || {};\n"
            "const publicados = data.publicados || [];\n"
            "// SHADOW: con el guard activo, /publicar DEV nunca llega a 06B -- 0 elegibles,\n"
            "// sin importar qué haya devuelto Python. Inactivo por defecto: cálculo de siempre.\n"
            "const elegibles = guardActivo ? [] : publicados.filter(function(c){ return c && c.ruta_sap_publicado && c.ruta_resultado_publicado && c.ruta_marker && c.sha256; });\n"
            "return [{ json: { elegibles: elegibles, hay_elegibles: elegibles.length > 0 } }];",
        ),
    ],
    "DECIDIR - Publicar GLOBAL oficial": [
        (
            "const debePublicar = modo === 'official' && r.estado === 'VALIDADO_PENDIENTE_PUBLICACION';",
            f"{_GUARD_JS_DECL}\n"
            "// SHADOW: con el guard activo, debe_publicar=false aunque el request diga modo='official'.\n"
            "const debePublicar = !guardActivo && modo === 'official' && r.estado === 'VALIDADO_PENDIENTE_PUBLICACION';",
        ),
    ],
    "DECIDIR - Publicar CONTROL1 oficial": [
        (
            "const r = $json.data || {};\nif (modo !== 'official') {",
            "const r = $json.data || {};\n"
            f"{_GUARD_JS_DECL}\n"
            "// SHADOW: con el guard activo, debe_publicar=false aunque el request diga modo='official'.\n"
            "if (guardActivo || modo !== 'official') {",
        ),
    ],
    "DECIDIR - Publicar GLOBAL institucional oficial": [
        (
            "const r = $json.data;\n"
            "// Solo se publica si LOS TRES (TIQ, AME e INSTITUCIONAL) llegaron a un GLOBAL\n"
            "// valido -- nunca institucional parcial: si TIQ o AME hubieran fallado, esta\n"
            "// rama nunca se ejecuta (dev_api.generar_global_institucional ya propaga la\n"
            "// excepcion antes de fusionar, ver INTERPRETAR->salida ERROR).\n"
            "const debePublicar = modo === 'official'\n"
            "  && r.resultado_tiq && r.resultado_tiq.estado === 'VALIDADO_PENDIENTE_PUBLICACION'\n"
            "  && r.resultado_ame && r.resultado_ame.estado === 'VALIDADO_PENDIENTE_PUBLICACION';",
            f"const r = $json.data;\n{_GUARD_JS_DECL}\n"
            "// SHADOW: con el guard activo, debe_publicar=false aunque el request diga modo='official'\n"
            "// (mismo criterio que 'DECIDIR - Publicar GLOBAL oficial').\n"
            "// Solo se publica si LOS TRES (TIQ, AME e INSTITUCIONAL) llegaron a un GLOBAL\n"
            "// valido -- nunca institucional parcial: si TIQ o AME hubieran fallado, esta\n"
            "// rama nunca se ejecuta (dev_api.generar_global_institucional ya propaga la\n"
            "// excepcion antes de fusionar, ver INTERPRETAR->salida ERROR).\n"
            "const debePublicar = !guardActivo && modo === 'official'\n"
            "  && r.resultado_tiq && r.resultado_tiq.estado === 'VALIDADO_PENDIENTE_PUBLICACION'\n"
            "  && r.resultado_ame && r.resultado_ame.estado === 'VALIDADO_PENDIENTE_PUBLICACION';",
        ),
    ],
    "DECIDIR - Publicar CONTROL3 oficial": [
        (
            "const vacio = { debe_publicar: false, hay_reporte: false, hay_reporte_json: false, hay_snapshots: false, hay_historico: false, hay_periodos: false };\n"
            "if (modo !== 'official' || r.resultado === 'ERROR' || r.estado === 'ERROR_TECNICO' || r.dry_run === true) {",
            f"{_GUARD_JS_DECL}\n"
            "const vacio = { debe_publicar: false, hay_reporte: false, hay_reporte_json: false, hay_snapshots: false, hay_historico: false, hay_periodos: false };\n"
            "// SHADOW: con el guard activo, debe_publicar=false aunque el request diga modo='official'.\n"
            "if (guardActivo || modo !== 'official' || r.resultado === 'ERROR' || r.estado === 'ERROR_TECNICO' || r.dry_run === true) {",
        ),
    ],
}


def aplicar_patches_backend(obj):
    nodos_por_nombre = {n["name"]: n for n in obj["nodes"]}
    aplicados = 0
    for nombre_nodo, patches in BACKEND_JSCODE_PATCHES.items():
        nodo = nodos_por_nombre.get(nombre_nodo)
        assert nodo is not None, f"nodo BACKEND no encontrado: {nombre_nodo!r}"
        codigo = nodo["parameters"]["jsCode"]
        for antes, despues in patches:
            ocurrencias = codigo.count(antes)
            assert ocurrencias == 1, (
                f"{nombre_nodo!r}: se esperaba exactamente 1 ocurrencia del patrón a "
                f"parchear, se encontraron {ocurrencias}"
            )
            codigo = codigo.replace(antes, despues)
            aplicados += 1
        nodo["parameters"]["jsCode"] = codigo
    return aplicados


# ---------------------------------------------------------------------------
# SHADOW — guarda de escritura en los 3 subworkflows que pueden tocar
# Drive (06B, 07D, 07E): un nodo Code nuevo, inmediatamente después de su
# Execute Workflow Trigger, ANTES de cualquier nodo googleDrive. IDs
# fijos (no aleatorios) para que el generador sea idempotente byte a
# byte entre corridas. No se toca ninguna otra conexión ni nodo — solo se
# reapunta la salida del trigger hacia la guarda, y la guarda hacia el
# destino original del trigger.
# ---------------------------------------------------------------------------

_GUARD_NODE_NAME = "GUARDIA SHADOW (bloquea si TIQ_BLOCK_OFFICIAL_PUBLISH)"
_GUARD_JSCODE = (
    "// SHADOW GUARD (migracion Railway, defensa en profundidad) -- ver\n"
    "// v3/shadow_guard.py para el equivalente en Python. Corre ANTES de\n"
    "// cualquier nodo Google Drive que pueda escribir en este subworkflow,\n"
    "// sin importar qué decidió el llamador (BACKEND). Inactiva por\n"
    "// defecto: sin la variable (o con cualquier valor que no sea\n"
    "// exactamente true/1/yes) este subworkflow se comporta exactamente\n"
    "// igual que antes de esta guarda.\n"
    "const valor = String($env.TIQ_BLOCK_OFFICIAL_PUBLISH || '').trim().toLowerCase();\n"
    "if (['true', '1', 'yes'].includes(valor)) {\n"
    "  throw new Error('PUBLICACION_OFICIAL_BLOQUEADA_POR_ENTORNO: TIQ_BLOCK_OFFICIAL_PUBLISH "
    "activo (entorno sombra/dev). Este subworkflow no puede escribir en Drive.');\n"
    "}\n"
    "return $input.all();"
)

SHADOW_GUARD_SUBWORKFLOWS = [
    {
        "archivo": "wcgxNei3duWfMDp1_06b_publicacion_oficial.json",
        "trigger": "ENTRADA (Execute Workflow Trigger)",
        "guard_id": "a1a1a1a1-0001-4a1a-9a1a-000000000001",
    },
    {
        "archivo": "HhuQCVP2oCubavzY_07d_publicar_oficial.json",
        "trigger": "ENTRADA (Execute Workflow Trigger)",
        "guard_id": "a1a1a1a1-0002-4a1a-9a1a-000000000002",
    },
    {
        "archivo": "Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json",
        "trigger": "ENTRADA (Execute Workflow Trigger)",
        "guard_id": "a1a1a1a1-0003-4a1a-9a1a-000000000003",
    },
]


def insertar_guardia_shadow(obj, trigger_name, guard_id):
    trigger = next((n for n in obj["nodes"] if n["name"] == trigger_name), None)
    assert trigger is not None, f"trigger no encontrado: {trigger_name!r}"
    tx, ty = trigger["position"]
    conexiones_trigger = obj["connections"].get(trigger_name)
    assert conexiones_trigger and conexiones_trigger.get("main"), (
        f"{trigger_name!r}: sin conexiones de salida — no se puede insertar la guarda"
    )
    destino_original = conexiones_trigger["main"][0]

    guard_node = {
        "parameters": {"jsCode": _GUARD_JSCODE},
        "id": guard_id,
        "name": _GUARD_NODE_NAME,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [tx + 200, ty],
    }
    obj["nodes"].append(guard_node)
    obj["connections"][trigger_name] = {"main": [[{"node": _GUARD_NODE_NAME, "type": "main", "index": 0}]]}
    obj["connections"][_GUARD_NODE_NAME] = {"main": [destino_original]}


BACKEND_WORKFLOW_FILE = "aLs1f3GMqswbaENA_backend_dev.json"
GUARD_INSERTIONS_BY_FILE = {g["archivo"]: g for g in SHADOW_GUARD_SUBWORKFLOWS}
GUARD_IDS_ESPERADOS = {g["archivo"]: g["guard_id"] for g in SHADOW_GUARD_SUBWORKFLOWS}


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

        cambios = sum(original.count(a) for a, _ in PRE_REPLACEMENTS + REPLACEMENTS)
        nodos_antes = {n["id"] for n in original_obj.get("nodes", [])}

        # SHADOW: hardening a nivel de objeto (secciones 7-8 de la migración).
        # Se aplica sobre adaptado_obj (después de la portabilidad de rutas),
        # y luego se vuelve a serializar — por eso reescribimos `adaptado`.
        if nombre == BACKEND_WORKFLOW_FILE:
            cambios += aplicar_patches_backend(adaptado_obj)
            adaptado = json.dumps(adaptado_obj, ensure_ascii=False, indent=2)
        elif nombre in GUARD_INSERTIONS_BY_FILE:
            g = GUARD_INSERTIONS_BY_FILE[nombre]
            insertar_guardia_shadow(adaptado_obj, g["trigger"], g["guard_id"])
            cambios += 1
            adaptado = json.dumps(adaptado_obj, ensure_ascii=False, indent=2)

        # Invariante de nodos: todo ID original debe seguir presente y sin
        # cambios; lo único que puede agregarse son las guardas SHADOW
        # deliberadamente insertadas en 06B/07D/07E (nunca en los demás).
        nodos_despues = {n["id"] for n in adaptado_obj.get("nodes", [])}
        assert nodos_antes.issubset(nodos_despues), f"{nombre}: un ID de nodo original desapareció"
        agregados = nodos_despues - nodos_antes
        esperado = {GUARD_IDS_ESPERADOS[nombre]} if nombre in GUARD_IDS_ESPERADOS else set()
        assert agregados == esperado, f"{nombre}: nodos agregados inesperados: {agregados - esperado}"

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

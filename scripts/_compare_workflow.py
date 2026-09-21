#!/usr/bin/env python3
"""scripts/_compare_workflow.py — comparación SEMÁNTICA de un workflow n8n
exportado (estado ACTUAL en Postgres) contra el snapshot deseado
(snapshots/railway-shadow/*.json), para scripts/sync_workflows_railway.sh.

Por qué existe: `n8n export:workflow`/`import:workflow` son opacos a texto
completo (incluyen versionId/activeVersionId/timestamps que cambian en
cada operación aunque el contenido real -- nodes/connections/settings --
sea idéntico). Comparar los archivos byte a byte produciría un "DIFFERENT"
en casi cualquier corrida, forzando un import+publish innecesario en cada
boot. Este módulo aísla la única lógica de decisión que sync_workflows_
railway.sh necesita, para poder probarla con pytest sin n8n real (ver
tests_v3/test_sync_workflows.py).

Decisión (idéntica a la especificación del bloque caja-america):
  - ABSENT:        no hay export actual (el workflow no existe en n8n).
  - DIFFERENT:     el contenido relevante (name/nodes/connections/settings)
                    no coincide con el snapshot.
  - NEEDS_PUBLISH: el contenido coincide, pero la versión activa del
                    workflow actual no es su versión más reciente
                    (versionId != activeVersionId) -- hace falta publicar,
                    no reimportar.
  - SAME:          contenido igual y ya publicado (versionId ==
                    activeVersionId, o el export no distingue ambos
                    campos -- entonces no hay nada que publicar).

Nunca decide NADA sobre credenciales: ese campo ni se lee ni se compara
aquí (las credenciales de los nodos se preservan tal cual las trae cada
archivo; ver n8n_frontend/... y SNAPSHOT_MANIFEST.md).
"""
import json
import sys

# Campos de nivel superior que SÍ importan para decidir si el contenido
# "real" del workflow cambió. Todo lo demás (id se compara aparte, no
# aquí) es metadata operativa de n8n, no contenido editado a mano.
CAMPOS_RELEVANTES = ("name", "nodes", "connections", "settings")

ABSENT = "ABSENT"
DIFFERENT = "DIFFERENT"
NEEDS_PUBLISH = "NEEDS_PUBLISH"
SAME = "SAME"


def _normalizar_nodo(nodo):
    """Un nodo tal cual, salvo que se ordenan sus claves (para que la
    serialización sea estable) -- ninguna clave de nodo se descarta: un
    parámetro cambiado SÍ debe contar como contenido distinto."""
    return json.loads(json.dumps(nodo, sort_keys=True, ensure_ascii=False))


def _normalizar(doc):
    """Subconjunto CANONICO y comparable de un documento de workflow
    (exportado o snapshot): solo CAMPOS_RELEVANTES, con la lista de nodos
    ordenada por `id` (nunca por posición en el array, que puede variar
    entre un export y otro sin que el contenido real haya cambiado)."""
    normalizado = {}
    for campo in CAMPOS_RELEVANTES:
        valor = doc.get(campo)
        if campo == "nodes" and isinstance(valor, list):
            valor = sorted((_normalizar_nodo(n) for n in valor), key=lambda n: n.get("id", ""))
        normalizado[campo] = valor
    return normalizado


def mismo_contenido(exportado, snapshot):
    """True si name/nodes/connections/settings son equivalentes entre el
    workflow exportado (estado actual) y el snapshot deseado -- ignora
    versionId/activeVersionId/createdAt/updatedAt/activeVersion y
    cualquier otro campo de metadata operativa."""
    return _normalizar(exportado) == _normalizar(snapshot)


def necesita_publicar(exportado):
    """True si el export trae versionId/activeVersionId y difieren (la
    versión activa del workflow no es su última versión guardada). Un
    export que no trae ninguno de los dos campos (formato clásico de n8n,
    sin versionado draft/publicado) nunca necesita publicar por este
    motivo: no hay dos versiones que reconciliar."""
    version_id = exportado.get("versionId")
    active_version_id = exportado.get("activeVersionId")
    if version_id is None and active_version_id is None:
        return False
    return version_id != active_version_id


def decidir(exportado, snapshot):
    """`exportado`: dict ya parseado del `n8n export:workflow` actual, o
    None si el workflow no existe todavia en esta instancia (comando
    fallido / sin salida). `snapshot`: dict ya parseado del JSON deseado
    (snapshots/railway-shadow/<archivo>.json). Devuelve una de las 4
    constantes de módulo; nunca lanza por una diferencia de contenido
    (eso es el resultado normal DIFFERENT, no un error)."""
    if exportado is None:
        return ABSENT
    if not mismo_contenido(exportado, snapshot):
        return DIFFERENT
    if necesita_publicar(exportado):
        return NEEDS_PUBLISH
    return SAME


def _desenvolver(doc, ruta):
    """`n8n export:workflow` (n8n 2.35.7) serializa una LISTA JSON incluso
    al exportar un solo workflow (`[ {...workflow...} ]`). Un dict directo
    (snapshot, o export de versiones anteriores de n8n) se acepta tal
    cual. Cualquier otro formato -- lista vacia, lista con mas de un
    elemento, o un tipo que no sea ni dict ni list -- falla CERRADO: nunca
    se reinterpreta silenciosamente como ABSENT ni como dict vacio."""
    if isinstance(doc, dict):
        return doc
    if isinstance(doc, list):
        if len(doc) != 1:
            raise ValueError(
                f"{ruta}: se esperaba una lista con exactamente 1 workflow, "
                f"se encontraron {len(doc)}"
            )
        elemento = doc[0]
        if not isinstance(elemento, dict):
            raise ValueError(f"{ruta}: el elemento de la lista no es un objeto de workflow")
        return elemento
    raise ValueError(f"{ruta}: formato de JSON inesperado ({type(doc).__name__}), se esperaba objeto o lista")


def _cargar_json(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return _desenvolver(doc, ruta)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2):
        print("uso: _compare_workflow.py <snapshot.json> [exportado.json]", file=sys.stderr)
        return 2

    snapshot = _cargar_json(argv[0])
    exportado = None
    if len(argv) == 2 and argv[1]:
        try:
            exportado = _cargar_json(argv[1])
        except (OSError, json.JSONDecodeError):
            exportado = None

    print(decidir(exportado, snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())

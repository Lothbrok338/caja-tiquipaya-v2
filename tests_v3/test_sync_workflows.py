"""tests_v3/test_sync_workflows.py — bloque caja-america, parte A.

Dos capas:
  1. scripts/_compare_workflow.py (decidir/mismo_contenido/necesita_publicar):
     unitarias puras, sin CLI ni subprocess.
  2. scripts/sync_workflows_railway.sh: integración con un `n8n` FALSO
     (un stub bash controlado por variables de entorno, ver `_escribir_n8n_falso`)
     que nunca toca Postgres real ni deja ningún proceso n8n corriendo --
     cada subcomando (export:workflow/import:workflow/update:workflow) es
     una invocación de una sola corrida, exactamente como el n8n real.

No requiere Drive, Railway, Postgres ni n8n instalado: todo corre contra
snapshots sintéticos y el stub de este archivo.

Uso: python -m pytest tests_v3/test_sync_workflows.py -q
"""
import json
import os
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts._compare_workflow as cw  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC_SCRIPT = os.path.join(REPO_ROOT, "scripts", "sync_workflows_railway.sh")


# ---------------------------------------------------------------------------
# 1) scripts/_compare_workflow.py -- unitarias puras
# ---------------------------------------------------------------------------

def _wf(nombre="X", nodes=None, connections=None, settings=None, **extra):
    doc = {
        "name": nombre,
        "nodes": nodes if nodes is not None else [{"id": "a", "name": "A", "parameters": {}}],
        "connections": connections if connections is not None else {},
        "settings": settings if settings is not None else {},
    }
    doc.update(extra)
    return doc


def test_mismo_contenido_ignora_versionId_activeVersionId_timestamps():
    a = _wf(versionId="v1", activeVersionId="v1", createdAt="2026-01-01", updatedAt="2026-01-02")
    b = _wf(versionId="v9", activeVersionId="v8", createdAt="2030-01-01", updatedAt="2030-01-02")
    assert cw.mismo_contenido(a, b) is True


def test_mismo_contenido_ignora_orden_de_nodos():
    n1 = {"id": "a", "name": "A", "parameters": {}}
    n2 = {"id": "b", "name": "B", "parameters": {}}
    a = _wf(nodes=[n1, n2])
    b = _wf(nodes=[n2, n1])
    assert cw.mismo_contenido(a, b) is True


def test_mismo_contenido_detecta_parametro_de_nodo_distinto():
    a = _wf(nodes=[{"id": "a", "name": "A", "parameters": {"jsCode": "1"}}])
    b = _wf(nodes=[{"id": "a", "name": "A", "parameters": {"jsCode": "2"}}])
    assert cw.mismo_contenido(a, b) is False


def test_necesita_publicar_true_cuando_difieren():
    assert cw.necesita_publicar({"versionId": "v2", "activeVersionId": "v1"}) is True


def test_necesita_publicar_false_cuando_coinciden():
    assert cw.necesita_publicar({"versionId": "v1", "activeVersionId": "v1"}) is False


def test_necesita_publicar_false_sin_campos_de_version():
    assert cw.necesita_publicar({}) is False


def test_decidir_absent_sin_export():
    assert cw.decidir(None, _wf()) == cw.ABSENT


def test_decidir_different_contenido_distinto():
    actual = _wf(nodes=[{"id": "a", "name": "A", "parameters": {"jsCode": "viejo"}}],
                 versionId="v1", activeVersionId="v1")
    deseado = _wf(nodes=[{"id": "a", "name": "A", "parameters": {"jsCode": "nuevo"}}])
    assert cw.decidir(actual, deseado) == cw.DIFFERENT


def test_decidir_needs_publish_contenido_igual_pero_no_publicado():
    actual = _wf(versionId="v2", activeVersionId="v1")
    deseado = _wf()
    assert cw.decidir(actual, deseado) == cw.NEEDS_PUBLISH


def test_decidir_same_contenido_igual_y_publicado():
    actual = _wf(versionId="v1", activeVersionId="v1")
    deseado = _wf()
    assert cw.decidir(actual, deseado) == cw.SAME


def test_main_cli_imprime_decision(tmp_path, capsys):
    snapshot = tmp_path / "s.json"
    snapshot.write_text(json.dumps(_wf(versionId="v1", activeVersionId="v1")), encoding="utf-8")
    assert cw.main([str(snapshot)]) == 0
    assert capsys.readouterr().out.strip() == cw.ABSENT

    exportado = tmp_path / "e.json"
    exportado.write_text(json.dumps(_wf(versionId="v1", activeVersionId="v1")), encoding="utf-8")
    assert cw.main([str(snapshot), str(exportado)]) == 0
    assert capsys.readouterr().out.strip() == cw.SAME


def test_cargar_json_desenvuelve_lista_de_un_elemento(tmp_path):
    """`n8n export:workflow` (n8n 2.35.7) serializa SIEMPRE una lista JSON,
    incluso para un solo workflow exportado -- debe desenvolverse igual
    que un dict directo."""
    doc = _wf(versionId="v1", activeVersionId="v1")
    ruta = tmp_path / "export_lista.json"
    ruta.write_text(json.dumps([doc]), encoding="utf-8")
    assert cw._cargar_json(str(ruta)) == doc


def test_cargar_json_lista_vacia_falla_cerrado(tmp_path):
    ruta = tmp_path / "export_vacio.json"
    ruta.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        cw._cargar_json(str(ruta))


def test_cargar_json_lista_con_mas_de_un_elemento_falla_cerrado(tmp_path):
    ruta = tmp_path / "export_multi.json"
    ruta.write_text(json.dumps([_wf(), _wf(nombre="Y")]), encoding="utf-8")
    with pytest.raises(ValueError):
        cw._cargar_json(str(ruta))


def test_cargar_json_tipo_inesperado_falla_cerrado(tmp_path):
    ruta = tmp_path / "export_invalido.json"
    ruta.write_text(json.dumps("no es un workflow"), encoding="utf-8")
    with pytest.raises(ValueError):
        cw._cargar_json(str(ruta))


# ---------------------------------------------------------------------------
# 2) scripts/sync_workflows_railway.sh -- integracion con un n8n FALSO.
# ---------------------------------------------------------------------------

_N8N_FALSO = """#!/usr/bin/env bash
# n8n FALSO de prueba -- nunca toca Postgres real, nunca deja nada
# corriendo (cada subcomando termina de inmediato, como el n8n real).
# export:workflow imita el formato REAL de n8n 2.35.7: siempre escribe
# una LISTA JSON `[ {...workflow...} ]`, incluso para un solo workflow.
set -euo pipefail
echo "$@" >> "$FAKE_N8N_LOG"

sub="$1"; shift
case "$sub" in
  export:workflow)
    if [ "${FAKE_N8N_EXPORT_EXIT:-0}" != "0" ]; then
      exit "${FAKE_N8N_EXPORT_EXIT}"
    fi
    output=""
    for arg in "$@"; do
      case "$arg" in --output=*) output="${arg#--output=}" ;; esac
    done
    python3 -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    doc = json.load(f)
with open(sys.argv[2], 'w', encoding='utf-8') as f:
    json.dump(doc if isinstance(doc, list) else [doc], f)
" "$FAKE_N8N_EXPORT_CONTENT" "$output"
    ;;
  import:workflow)
    exit "${FAKE_N8N_IMPORT_EXIT:-0}"
    ;;
  publish:workflow)
    exit "${FAKE_N8N_PUBLISH_EXIT:-0}"
    ;;
  *)
    echo "n8n falso: subcomando no soportado: $sub" >&2
    exit 9
    ;;
esac
"""


def _escribir_n8n_falso(bin_dir):
    ruta = os.path.join(bin_dir, "n8n")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(_N8N_FALSO)
    st = os.stat(ruta)
    os.chmod(ruta, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return ruta


def _correr_sync(tmp_path, snapshot_doc, env_extra):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _escribir_n8n_falso(str(bin_dir))

    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir()
    (snapshots_dir / "wf.json").write_text(json.dumps(snapshot_doc), encoding="utf-8")

    export_content = tmp_path / "export_content.json"
    export_content.write_text(json.dumps(env_extra.pop("_export_doc", snapshot_doc)), encoding="utf-8")

    log = tmp_path / "n8n_calls.log"
    log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["TIQ_WORKFLOWS_SNAPSHOTS_DIR"] = str(snapshots_dir)
    env["FAKE_N8N_LOG"] = str(log)
    env["FAKE_N8N_EXPORT_CONTENT"] = str(export_content)
    env.update(env_extra)

    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    llamadas = log.read_text(encoding="utf-8").splitlines()
    return r, llamadas


def test_sync_same_publicado_skip(tmp_path):
    doc = _wf(nombre="WF-1", **{"id": "id-1"})
    r, llamadas = _correr_sync(tmp_path, doc, {
        "_export_doc": _wf(nombre="WF-1", id="id-1", versionId="v1", activeVersionId="v1"),
    })
    assert r.returncode == 0, r.stderr
    assert "[workflow-sync] OK id-1" in r.stdout
    assert not any(l.startswith("import:workflow") for l in llamadas)
    assert not any(l.startswith("publish:workflow") for l in llamadas)


def test_sync_igual_no_publicado_solo_publica(tmp_path):
    doc = _wf(nombre="WF-1", **{"id": "id-1"})
    r, llamadas = _correr_sync(tmp_path, doc, {
        "_export_doc": _wf(nombre="WF-1", id="id-1", versionId="v2", activeVersionId="v1"),
    })
    assert r.returncode == 0, r.stderr
    assert "UPDATED id-1" in r.stdout and "publicado (el contenido ya coincidia)" in r.stdout
    assert not any(l.startswith("import:workflow") for l in llamadas)
    publishes = [l for l in llamadas if l.startswith("publish:workflow")]
    assert len(publishes) == 1
    assert "--id=id-1" in publishes[0]


def test_sync_diferente_importa_y_publica(tmp_path):
    doc = _wf(nombre="WF-1", nodes=[{"id": "a", "name": "A", "parameters": {"jsCode": "nuevo"}}], id="id-1")
    r, llamadas = _correr_sync(tmp_path, doc, {
        "_export_doc": _wf(nombre="WF-1", nodes=[{"id": "a", "name": "A", "parameters": {"jsCode": "viejo"}}],
                            id="id-1", versionId="v1", activeVersionId="v1"),
    })
    assert r.returncode == 0, r.stderr
    assert "UPDATED id-1" in r.stdout and "contenido distinto, importado y publicado" in r.stdout
    imports = [l for l in llamadas if l.startswith("import:workflow")]
    assert len(imports) == 1
    publishes = [l for l in llamadas if l.startswith("publish:workflow")]
    assert len(publishes) == 1


def test_sync_ausente_importa_y_publica(tmp_path):
    doc = _wf(nombre="WF-1", id="id-1")
    r, llamadas = _correr_sync(tmp_path, doc, {"FAKE_N8N_EXPORT_EXIT": "1"})
    assert r.returncode == 0, r.stderr
    assert "UPDATED id-1" in r.stdout and "no existia, importado y publicado" in r.stdout
    assert any(l.startswith("import:workflow") for l in llamadas)
    assert len([l for l in llamadas if l.startswith("publish:workflow")]) == 1


def test_sync_error_de_n8n_aborta_con_exit_distinto_de_cero(tmp_path):
    doc = _wf(nombre="WF-1", id="id-1")
    r, _ = _correr_sync(tmp_path, doc, {"FAKE_N8N_EXPORT_EXIT": "1", "FAKE_N8N_IMPORT_EXIT": "1"})
    assert r.returncode != 0


def test_sync_nunca_deja_un_n8n_start_corriendo():
    """El script solo invoca subcomandos de una sola corrida (export/import/
    update:workflow) -- nunca `n8n start` ni nada que deje un proceso
    escuchando (eso rompería el modelo on-demand/sleep de GestorN8N)."""
    lineas_codigo = [l for l in open(SYNC_SCRIPT, encoding="utf-8") if not l.strip().startswith("#")]
    texto_codigo = "".join(lineas_codigo)
    assert "n8n start" not in texto_codigo
    assert "export:workflow" in texto_codigo and "import:workflow" in texto_codigo and "publish:workflow" in texto_codigo


# ---------------------------------------------------------------------------
# railway_entrypoint.sh llama al sync ANTES de servir el frontend.
# ---------------------------------------------------------------------------

def test_entrypoint_llama_sync_antes_del_frontend():
    ruta = os.path.join(REPO_ROOT, "scripts", "railway_entrypoint.sh")
    lineas = open(ruta, encoding="utf-8").read().splitlines()
    idx_sync = next(i for i, l in enumerate(lineas) if "sync_workflows_railway.sh" in l and l.strip().startswith("bash"))
    idx_frontend = next(i for i, l in enumerate(lineas) if "serve_v3_frontend.py" in l and l.strip().startswith("exec"))
    assert idx_sync < idx_frontend


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

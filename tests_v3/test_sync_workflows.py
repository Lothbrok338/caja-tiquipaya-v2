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
    env["DB_TYPE"] = "postgresdb"
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
# El sync corre UNA vez por deploy (preDeployCommand), no en el arranque.
# ---------------------------------------------------------------------------

def _codigo_sin_comentarios(ruta):
    with open(ruta, encoding="utf-8") as f:
        return "".join(l for l in f if not l.strip().startswith("#"))


def test_entrypoint_ya_no_llama_al_sync():
    """El despertar normal (Serverless Sleep) no debe reimportar ni
    publicar workflows: el entrypoint no referencia el script de sync."""
    codigo = _codigo_sin_comentarios(os.path.join(REPO_ROOT, "scripts", "railway_entrypoint.sh"))
    assert "sync_workflows_railway" not in codigo
    assert "import:workflow" not in codigo and "publish:workflow" not in codigo


def test_railway_json_no_define_el_predeploy():
    """El pre-deploy vive en la configuracion del SERVICIO en Railway (un
    servicio nuevo no lee railway.json y Config as Code deja de leerse el
    2026-12-01). railway.json no debe llevar una segunda copia que pueda
    divergir; el resto de su contenido queda exactamente como estaba."""
    with open(os.path.join(REPO_ROOT, "railway.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    assert "preDeployCommand" not in cfg["deploy"]
    assert cfg["build"] == {"builder": "DOCKERFILE", "dockerfilePath": "Dockerfile"}
    assert cfg["deploy"] == {
        "numReplicas": 1,
        "restartPolicyType": "ON_FAILURE",
        "restartPolicyMaxRetries": 5,
        "healthcheckPath": "/healthz",
    }


def test_sync_falla_cerrado_a_mitad_no_sigue_ni_declara_exito(tmp_path):
    """Si un import falla en el pre-deploy, el script termina con codigo
    != 0 en ese workflow: no publica ese id, no toca los siguientes y no
    imprime la linea de exito que se verifica en los logs del deploy."""
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    for i in (1, 2, 3):
        doc = _wf(nombre="WF-%d" % i, id="id-%d" % i)
        (snapshots / ("wf%d.json" % i)).write_text(json.dumps(doc), encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    n8n = bin_dir / "n8n"
    n8n.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$@" >> "$FAKE_N8N_LOG"\n'
        'case "$1" in\n'
        "  export:workflow) exit 1 ;;\n"   # ABSENT -> import + publish
        '  import:workflow) case "$*" in *wf2.json*) exit 1 ;; esac ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    n8n.chmod(0o755)
    log = tmp_path / "n8n.log"
    log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["TIQ_WORKFLOWS_SNAPSHOTS_DIR"] = str(snapshots)
    env["DB_TYPE"] = "postgresdb"
    env["FAKE_N8N_LOG"] = str(log)
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)

    llamadas = log.read_text(encoding="utf-8")
    assert r.returncode != 0
    assert "[workflow-sync] listo" not in r.stdout
    assert "import:workflow --input=%s" % (snapshots / "wf1.json") in llamadas  # el primero si se aplico
    assert "publish:workflow --id=id-1" in llamadas
    assert "publish:workflow --id=id-2" not in llamadas          # el que fallo no se publica
    # los siguientes no se ESCRIBEN (el pre-chequeo si los LEYO: solo export)
    assert "wf3.json" not in llamadas and "publish:workflow --id=id-3" not in llamadas


# ---------------------------------------------------------------------------
# PRE-CHEQUEO: todo lo detectable sin escribir aborta con CERO escrituras.
# ---------------------------------------------------------------------------

_N8N_POR_ID = """#!/usr/bin/env bash
# n8n falso: export:workflow devuelve el contenido de $FAKE_EXPORTS/<id>.json
# si existe (si no, falla = ABSENT); registra TODA llamada en orden.
echo "$@" >> "$FAKE_N8N_LOG"
sub="$1"; shift
case "$sub" in
  export:workflow)
    id=""; out=""
    for a in "$@"; do case "$a" in --id=*) id="${a#--id=}";; --output=*) out="${a#--output=}";; esac; done
    [ -f "$FAKE_EXPORTS/$id.json" ] || exit 1
    cp "$FAKE_EXPORTS/$id.json" "$out"
    ;;
  import:workflow|publish:workflow) exit 0 ;;
  *) exit 9 ;;
esac
"""


def _preparar_precheck(tmp_path, snapshots, exports=None):
    """snapshots: {archivo: contenido_str}; exports: {id: contenido_str}."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    n8n = bin_dir / "n8n"
    n8n.write_text(_N8N_POR_ID, encoding="utf-8")
    n8n.chmod(0o755)
    sdir = tmp_path / "snapshots"
    sdir.mkdir()
    for nombre, contenido in snapshots.items():
        (sdir / nombre).write_text(contenido, encoding="utf-8")
    edir = tmp_path / "exports"
    edir.mkdir()
    for wid, contenido in (exports or {}).items():
        (edir / (wid + ".json")).write_text(contenido, encoding="utf-8")
    log = tmp_path / "n8n.log"
    log.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["TIQ_WORKFLOWS_SNAPSHOTS_DIR"] = str(sdir)
    env["DB_TYPE"] = "postgresdb"
    env["FAKE_N8N_LOG"] = str(log)
    env["FAKE_EXPORTS"] = str(edir)
    return env, log


def _escrituras(log):
    return [l for l in log.read_text(encoding="utf-8").splitlines()
            if l.startswith("import:workflow") or l.startswith("publish:workflow")]


def _snap(i, **extra):
    return json.dumps(_wf(nombre="WF-%d" % i, id="id-%d" % i, **extra))


def test_precheck_json_invalido_en_el_tercero_aborta_sin_escrituras(tmp_path):
    env, log = _preparar_precheck(tmp_path, {
        "wf1.json": _snap(1), "wf2.json": _snap(2), "wf3.json": "{no es json",
    })
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert _escrituras(log) == [], "el pre-chequeo debe abortar ANTES de la primera escritura"
    assert "[workflow-sync] listo" not in r.stdout


def test_precheck_snapshot_sin_id_aborta_sin_escrituras(tmp_path):
    sin_id = json.dumps({"name": "WF-3", "nodes": [], "connections": {}, "settings": {}})
    env, log = _preparar_precheck(tmp_path, {"wf1.json": _snap(1), "wf2.json": _snap(2), "wf3.json": sin_id})
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and _escrituras(log) == []


def test_precheck_id_repetido_aborta_sin_escrituras(tmp_path):
    env, log = _preparar_precheck(tmp_path, {"wf1.json": _snap(1), "wf2.json": _snap(1)})
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "id repetido" in r.stderr and _escrituras(log) == []


def test_precheck_export_con_formato_inesperado_aborta_sin_escrituras(tmp_path):
    """Un export con 2 workflows en la lista (formato invalido) en el 3.º:
    antes se habrian aplicado el 1.º y el 2.º y recien ahi abortado."""
    env, log = _preparar_precheck(
        tmp_path,
        {"wf1.json": _snap(1), "wf2.json": _snap(2), "wf3.json": _snap(3)},
        exports={"id-3": json.dumps([json.loads(_snap(3)), json.loads(_snap(3))])},
    )
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert _escrituras(log) == []


def test_todas_las_lecturas_ocurren_antes_de_cualquier_escritura(tmp_path):
    env, log = _preparar_precheck(tmp_path, {"wf%d.json" % i: _snap(i) for i in (1, 2, 3)})
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    subs = [l.split()[0] for l in log.read_text(encoding="utf-8").splitlines()]
    primera_escritura = next(i for i, s in enumerate(subs) if s != "export:workflow")
    assert subs[:primera_escritura] == ["export:workflow"] * 3
    assert "export:workflow" not in subs[primera_escritura:]
    assert "pre-chequeo OK: 3 workflow(s)" in r.stdout


def test_sin_postgres_como_destino_aborta_sin_llamar_a_n8n(tmp_path):
    """Sin DB_TYPE=postgresdb n8n usaria SQLite efimero en el contenedor de
    pre-deploy y el sync 'tendria exito' sin tocar el Postgres real."""
    env, log = _preparar_precheck(tmp_path, {"wf1.json": _snap(1)})
    for valor in (None, "sqlite"):
        if valor is None:
            env.pop("DB_TYPE", None)
        else:
            env["DB_TYPE"] = valor
        r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
        assert r.returncode != 0 and "postgresdb" in r.stderr
        assert log.read_text(encoding="utf-8") == "", "ni siquiera debe leer de n8n"


def test_requisito_postgres_se_puede_desactivar_explicitamente(tmp_path):
    env, log = _preparar_precheck(tmp_path, {"wf1.json": _snap(1)})
    env.pop("DB_TYPE", None)
    env["TIQ_SYNC_REQUIRE_POSTGRES"] = "false"
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_precheck_con_los_8_snapshots_reales_y_n8n_falso(tmp_path):
    """Los 8 snapshots versionados de railway-shadow pasan el pre-chequeo:
    8 lecturas, y recien despues 8 import + 8 publish (n8n FALSO, sin red)."""
    reales = os.path.join(REPO_ROOT, "snapshots", "railway-shadow")
    contenidos = {f: open(os.path.join(reales, f), encoding="utf-8").read()
                  for f in sorted(os.listdir(reales)) if f.endswith(".json")}
    assert len(contenidos) == 8
    env, log = _preparar_precheck(tmp_path, contenidos)
    r = subprocess.run(["bash", SYNC_SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    subs = [l.split()[0] for l in log.read_text(encoding="utf-8").splitlines()]
    assert subs[:8] == ["export:workflow"] * 8
    assert subs[8:].count("import:workflow") == 8 and subs[8:].count("publish:workflow") == 8
    assert "listo: 8 workflow(s) sincronizados" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

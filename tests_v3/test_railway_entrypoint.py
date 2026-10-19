"""tests_v3/test_railway_entrypoint.py — migración Railway 2026-09.

Fix mínimo: n8n fallaba antes de invocar Python porque
${TIQ_BASE_DIR}/tiq_v3_tmp no existía todavía en un contenedor nuevo.
Verifica que scripts/railway_entrypoint.sh crea ese directorio ANTES de
arrancar el proceso principal, y que la línea realmente funciona si se
ejecuta (no solo que el texto esté presente).

Serverless Sleep (2026-09): el entrypoint ya NO arranca n8n (arrancaba
siempre en background y le impedía a Railway `sleepApplication` dormir
el contenedor de verdad). Ahora n8n arranca bajo demanda desde
scripts/serve_v3_frontend.py (GestorN8N, ver tests_v3/test_n8n_lazy_lifecycle.py)
y este archivo solo verifica que el entrypoint ya no lo toque.

No requiere Docker/Railway/n8n: corre bash directamente sobre un
tmp_path local.

Uso: python -m pytest tests_v3/test_railway_entrypoint.py -q
"""
import json
import os
import re
import socket
import subprocess
import time
import urllib.request

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINT = os.path.join(RAIZ, "scripts", "railway_entrypoint.sh")

_MKDIR_LINEA = 'mkdir -p "${TIQ_BASE_DIR:-/app/dev_workdir}/tiq_v3_tmp"'


def _contenido():
    with open(ENTRYPOINT, encoding="utf-8") as f:
        return f.read()


def test_mkdir_tiq_v3_tmp_presente_una_sola_vez():
    contenido = _contenido()
    assert contenido.count(_MKDIR_LINEA) == 1


def test_mkdir_ocurre_antes_del_exec_final():
    contenido = _contenido()
    pos_mkdir = contenido.index(_MKDIR_LINEA)
    pos_exec = contenido.index("exec python3 /app/scripts/serve_v3_frontend.py")
    assert pos_mkdir < pos_exec, "el directorio debe crearse ANTES de entregarle el control a Python"


def test_mkdir_crea_realmente_el_directorio_runtime(tmp_path):
    """Ejecuta la línea real del entrypoint (extraída, no reescrita a
    mano) contra un TIQ_BASE_DIR de prueba y confirma que el directorio
    que n8n necesita (tiq_v3_tmp) queda creado."""
    base_dir = tmp_path / "dev_workdir_test"
    assert not base_dir.exists()

    env = dict(os.environ)
    env["TIQ_BASE_DIR"] = str(base_dir)
    r = subprocess.run(["bash", "-c", _MKDIR_LINEA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    ruta_esperada = base_dir / "tiq_v3_tmp"
    assert ruta_esperada.is_dir()


def test_mkdir_usa_default_cuando_tiq_base_dir_no_esta_fijada():
    """Sin TIQ_BASE_DIR, el default es /app/dev_workdir (mismo que el
    resto del sistema — ver Dockerfile). No se ejecuta contra /app en
    este entorno de test; solo se resuelve la expresión del shell."""
    env = dict(os.environ)
    env.pop("TIQ_BASE_DIR", None)
    r = subprocess.run(
        ["bash", "-c", 'echo "${TIQ_BASE_DIR:-/app/dev_workdir}/tiq_v3_tmp"'],
        env=env, capture_output=True, text=True,
    )
    assert r.stdout.strip() == "/app/dev_workdir/tiq_v3_tmp"


def test_entrypoint_ya_no_arranca_n8n_directamente():
    """Guarda de alcance de la migración a n8n bajo demanda (Serverless
    Sleep, 2026-09): el entrypoint ya NO arranca n8n el mismo -- eso lo
    hace GestorN8N en scripts/serve_v3_frontend.py, bajo demanda, para
    que Railway sleepApplication pueda dormir el contenedor de verdad.
    El resto del entrypoint (guarda TIQ_BLOCK_OFFICIAL_PUBLISH, mkdir de
    tiq_v3_tmp, exec del proxy en foreground) sigue intacto."""
    contenido = _contenido()
    assert "TIQ_BLOCK_OFFICIAL_PUBLISH" in contenido
    assert "start_n8n.sh" not in contenido
    assert _MKDIR_LINEA in contenido
    assert "exec python3 /app/scripts/serve_v3_frontend.py" in contenido
    assert re.search(r"^set -euo pipefail$", contenido, re.MULTILINE)


# ---------------------------------------------------------------------------
# Arranque rapido: el despertar normal ya no sincroniza workflows (el sync
# corre como preDeployCommand, ver railway.json y DEPLOY_RAILWAY.md §7B).
# Estas pruebas ejecutan el entrypoint REAL (copia con /app/ -> raiz del
# repo, nada mas) con un `n8n` falso que registra cada llamada.
# ---------------------------------------------------------------------------

_N8N_REGISTRADOR = """#!/usr/bin/env bash
echo "$@" >> "$FAKE_N8N_LOG"
if [ -n "${FAKE_N8N_FALLA_EN:-}" ] && [ "$1" = "$FAKE_N8N_FALLA_EN" ]; then exit 1; fi
if [ "$1" = "export:workflow" ]; then exit 1; fi
exit 0
"""


@pytest.fixture
def sandbox(tmp_path):
    """Entrypoint real con rutas /app/ apuntando al repo + n8n falso."""
    original = _contenido()
    parcheado = original.replace("/app/", RAIZ + "/")
    assert parcheado != original and "/app/" not in parcheado
    entrypoint = tmp_path / "railway_entrypoint.sh"
    entrypoint.write_text(parcheado, encoding="utf-8")
    entrypoint.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    n8n = bin_dir / "n8n"
    n8n.write_text(_N8N_REGISTRADOR, encoding="utf-8")
    n8n.chmod(0o755)

    log = tmp_path / "n8n.log"
    log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["FAKE_N8N_LOG"] = str(log)
    env["TIQ_BASE_DIR"] = str(tmp_path / "dev_workdir")
    env["TIQ_BLOCK_OFFICIAL_PUBLISH"] = "true"
    for k in ("TIQ_AUTH_USERNAME", "TIQ_AUTH_PASSWORD"):
        env.pop(k, None)

    def llamadas_n8n():
        return [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]

    return {"entrypoint": str(entrypoint), "env": env, "llamadas_n8n": llamadas_n8n, "tmp": tmp_path}


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_arranque_normal_sirve_el_proxy_sin_sincronizar_workflows(sandbox):
    env = dict(sandbox["env"])
    puerto = _puerto_libre()
    env["PORT"] = str(puerto)

    t0 = time.monotonic()
    proc = subprocess.Popen(
        ["bash", sandbox["entrypoint"]], env=env, cwd=str(sandbox["tmp"]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        estado = None
        while time.monotonic() - t0 < 30:
            assert proc.poll() is None, "el entrypoint termino antes de servir: " + proc.stderr.read()
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/healthz" % puerto, timeout=1) as resp:
                    estado, cuerpo = resp.status, resp.read()
                break
            except OSError:
                time.sleep(0.05)
        tiempo = time.monotonic() - t0
        assert estado == 200 and cuerpo == b"OK"
        # Antes: ~107-115 s de sync en cada despertar. Ahora el proxy
        # responde en cuanto Python levanta.
        assert tiempo < 10, "el proxy tardo %.1f s en responder /healthz" % tiempo
        print("healthz 200 en %.2f s tras lanzar el entrypoint" % tiempo)
        # Ni una sola llamada a n8n (ni export, ni import, ni publish, ni start).
        assert sandbox["llamadas_n8n"]() == []
        # El directorio que necesita el backend sigue creandose.
        assert os.path.isdir(os.path.join(env["TIQ_BASE_DIR"], "tiq_v3_tmp"))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_con_argumentos_el_entrypoint_ejecuta_y_sale_sin_arrancar_el_proxy(sandbox):
    r = subprocess.run(
        ["bash", sandbox["entrypoint"], "bash", "-c", "echo comando-recibido; exit 0"],
        env=sandbox["env"], capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0 and "comando-recibido" in r.stdout
    r = subprocess.run(
        ["bash", sandbox["entrypoint"], "bash", "-c", "exit 7"],
        env=sandbox["env"], capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 7, "el codigo de salida del comando debe propagarse tal cual"


def _comando_predeploy_local():
    with open(os.path.join(RAIZ, "railway.json"), encoding="utf-8") as f:
        cmd = json.load(f)["deploy"]["preDeployCommand"][0]
    parcheado = cmd.replace("/app/", RAIZ + "/")
    assert parcheado != cmd
    return parcheado


def _snapshots_sinteticos(tmp):
    d = tmp / "snapshots"
    d.mkdir()
    for i in (1, 2):
        doc = {"id": "id-%d" % i, "name": "WF-%d" % i, "nodes": [], "connections": {}, "settings": {}}
        (d / ("wf%d.json" % i)).write_text(json.dumps(doc), encoding="utf-8")
    return str(d)


@pytest.mark.parametrize("via_entrypoint", [False, True])
def test_predeploy_exitoso_sincroniza_y_sale_con_cero(sandbox, via_entrypoint):
    """El comando EXACTO de railway.json funciona tanto si Railway lo
    ejecuta directamente como si lo entrega como argumentos al ENTRYPOINT."""
    env = dict(sandbox["env"])
    env["TIQ_WORKFLOWS_SNAPSHOTS_DIR"] = _snapshots_sinteticos(sandbox["tmp"])
    comando = _comando_predeploy_local()
    argv = ["bash", sandbox["entrypoint"]] + comando.split() if via_entrypoint else ["bash", "-c", comando]
    r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[workflow-sync] listo: 2 workflow(s) sincronizados" in r.stdout
    llamadas = sandbox["llamadas_n8n"]()
    assert sum(l.startswith("import:workflow") for l in llamadas) == 2
    assert sum(l.startswith("publish:workflow") for l in llamadas) == 2


@pytest.mark.parametrize("via_entrypoint", [False, True])
def test_predeploy_fallido_sale_distinto_de_cero_y_no_declara_exito(sandbox, via_entrypoint):
    """Fail closed: un fallo del sync hace que el pre-deploy termine con
    codigo != 0 (Railway no avanza el deploy) y que el contenedor de
    pre-deploy no llegue a servir nada."""
    env = dict(sandbox["env"])
    env["TIQ_WORKFLOWS_SNAPSHOTS_DIR"] = _snapshots_sinteticos(sandbox["tmp"])
    env["FAKE_N8N_FALLA_EN"] = "import:workflow"
    comando = _comando_predeploy_local()
    argv = ["bash", sandbox["entrypoint"]] + comando.split() if via_entrypoint else ["bash", "-c", comando]
    r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "[workflow-sync] listo" not in r.stdout
    assert not any(l.startswith("publish:workflow") for l in sandbox["llamadas_n8n"]())

"""tests_v3/test_railway_entrypoint.py — migración Railway 2026-09.

Fix mínimo: n8n fallaba antes de invocar Python porque
${TIQ_BASE_DIR}/tiq_v3_tmp no existía todavía en un contenedor nuevo.
Verifica que scripts/railway_entrypoint.sh crea ese directorio ANTES de
arrancar n8n, y que la línea realmente funciona si se ejecuta (no solo
que el texto esté presente).

No requiere Docker/Railway/n8n: corre bash directamente sobre un
tmp_path local.

Uso: python -m pytest tests_v3/test_railway_entrypoint.py -q
"""
import os
import re
import subprocess

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINT = os.path.join(RAIZ, "scripts", "railway_entrypoint.sh")

_MKDIR_LINEA = 'mkdir -p "${TIQ_BASE_DIR:-/app/dev_workdir}/tiq_v3_tmp"'


def _contenido():
    with open(ENTRYPOINT, encoding="utf-8") as f:
        return f.read()


def test_mkdir_tiq_v3_tmp_presente_una_sola_vez():
    contenido = _contenido()
    assert contenido.count(_MKDIR_LINEA) == 1


def test_mkdir_ocurre_antes_de_arrancar_n8n():
    contenido = _contenido()
    pos_mkdir = contenido.index(_MKDIR_LINEA)
    pos_start_n8n = contenido.index("start_n8n.sh")
    assert pos_mkdir < pos_start_n8n, "el directorio debe crearse ANTES de arrancar n8n"


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


def test_no_se_toco_nada_mas_del_entrypoint():
    """Guarda de alcance: el fix es exclusivamente esta línea — el resto
    del entrypoint (guarda TIQ_BLOCK_OFFICIAL_PUBLISH, arranque de n8n en
    background, cleanup, exec del proxy en foreground) sigue intacto."""
    contenido = _contenido()
    assert "TIQ_BLOCK_OFFICIAL_PUBLISH" in contenido
    assert "bash /app/scripts/start_n8n.sh &" in contenido
    assert "exec python3 /app/scripts/serve_v3_frontend.py" in contenido
    assert re.search(r"^set -euo pipefail$", contenido, re.MULTILINE)

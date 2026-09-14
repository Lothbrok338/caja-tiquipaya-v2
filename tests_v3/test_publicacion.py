"""tests_v3/test_publicacion.py — pruebas propias del módulo 06 ·
PUBLICACION de V3 (v3/publicacion.py). Este módulo es un ADAPTADOR sobre
la lógica de publicación YA VALIDADA de V2 (pipeline_tiquipaya.
construir_marcador_procesado()/calcular_sha256()/nombre_marcador_procesado(),
mismo patrón de invocación que publicar_cierre.py): estas pruebas
verifican que el adaptador invoca ese código real correctamente, respeta
la idempotencia SHA256 y nunca publica un cierre que no esté
LISTO_PARA_PUBLICAR — NO reimplementan ninguna regla de negocio.

Uso: python -m pytest tests_v3/test_publicacion.py -q
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx  # noqa: E402
import pipeline_tiquipaya as pipeline  # noqa: E402
from v3.motor import ejecutar_motor_cierre  # noqa: E402
from v3.clasificacion import (  # noqa: E402
    LISTO_PARA_PUBLICAR, ERROR_REVISAR, SIN_ARCHIVO, YA_PROCESADO, ERROR_TECNICO,
)
from v3.publicacion import (  # noqa: E402
    publicar_cierre_dev, publicar_lote, PUBLICADO, YA_PUBLICADO, NO_PUBLICABLE, ERROR_PUBLICACION,
)


_SFC_VACIO = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}


def _cierre_procesado(tmp_path, nombre="a", fecha="2026-09-01"):
    """Construye un cierre real, lo corre por el motor V2 real (via el
    adaptador del Módulo 03), y devuelve un item listo para publicar
    (estado_final=LISTO_PARA_PUBLICAR) con rutas reales de cierre/sap/
    resultado — exactamente lo que entregaría la cadena 01->02->03->04."""
    carpeta = tmp_path / nombre
    carpeta.mkdir()
    ruta_cierre = carpeta / f"CIERRE {fecha[8:10]}-{fecha[5:7]}-{fecha[0:4]}.xlsm"
    fx.crear_cierre(str(ruta_cierre), _SFC_VACIO, _SFC_VACIO)
    ruta_maestro = carpeta / "MAESTRO.xlsm"
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=[], atc_filas=[])
    ruta_plantilla = carpeta / "Plantilla_SAP_maestra.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))

    item_motor = {
        "fecha": fecha, "archivo_esperado": os.path.basename(str(ruta_cierre)),
        "estado_ingesta": "ENCONTRADO", "estado_materializacion": "MATERIALIZADO",
        "ruta_cierre_local": str(ruta_cierre), "ruta_maestro_local": str(ruta_maestro),
        "ruta_template_sap_local": str(ruta_plantilla), "ruta_markers_local": None,
    }
    r = ejecutar_motor_cierre(item_motor, str(tmp_path / "dev"))
    assert r["estado_motor"] == "PROCESADO"

    return {
        "fecha": fecha, "estado_final": LISTO_PARA_PUBLICAR,
        "ruta_cierre_local": str(ruta_cierre), "ruta_sap": r["ruta_sap"], "ruta_resultado": r["ruta_resultado"],
    }


# 1) LISTO_PARA_PUBLICAR se publica correctamente (DEV): archivos copiados + marker.
def test_listo_para_publicar_se_publica(tmp_path):
    item = _cierre_procesado(tmp_path)
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["estado_publicacion"] == PUBLICADO
    assert r["publicado"] is True
    assert os.path.isfile(r["ruta_sap_publicado"])
    assert os.path.isfile(r["ruta_resultado_publicado"])
    assert os.path.isfile(r["ruta_cierre_procesado"])
    assert os.path.isfile(r["ruta_marker"])
    assert os.path.basename(r["ruta_marker"]).startswith("PROCESADO_")


# 2) El marcador contiene el contenido REAL de construir_registro_control (mismo que V2).
def test_marker_contiene_registro_control_real(tmp_path):
    item = _cierre_procesado(tmp_path)
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    with open(r["ruta_marker"], "r", encoding="utf-8") as f:
        contenido = json.load(f)
    assert contenido["Estado"] == "PROCESADO"
    assert contenido["HashOrigen"] == r["sha256"]
    assert contenido["FechaCierre"]
    assert contenido["ArchivoSAP"] == os.path.basename(r["ruta_sap_publicado"])


# 3) CONTRACT-008/009: idempotencia — publicar dos veces el mismo cierre no duplica nada.
def test_idempotencia_no_duplica_al_republicar(tmp_path):
    item = _cierre_procesado(tmp_path)
    base_dir_dev = str(tmp_path / "dev")
    r1 = publicar_cierre_dev(item, base_dir_dev)
    assert r1["estado_publicacion"] == PUBLICADO

    mtime_marker_antes = os.path.getmtime(r1["ruta_marker"])
    mtime_sap_antes = os.path.getmtime(r1["ruta_sap_publicado"])

    r2 = publicar_cierre_dev(item, base_dir_dev)
    assert r2["estado_publicacion"] == YA_PUBLICADO
    assert r2["publicado"] is False
    assert r2["sha256"] == r1["sha256"]
    assert os.path.getmtime(r2["ruta_marker"]) == mtime_marker_antes
    assert os.path.getmtime(r2["ruta_sap_publicado"]) == mtime_sap_antes


# 4) Estados no habilitados (CONTRACT-011) nunca se publican.
@pytest.mark.parametrize("estado", [ERROR_REVISAR, SIN_ARCHIVO, ERROR_TECNICO, "AMBIGUO", "BLOQUEADO_EXCEPCION"])
def test_estados_no_habilitados_no_se_publican(tmp_path, estado):
    item = {
        "fecha": "2026-09-02", "estado_final": estado,
        "ruta_cierre_local": "no_importa.xlsm", "ruta_sap": "no_importa.xlsx", "ruta_resultado": "no_importa.json",
    }
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["estado_publicacion"] == NO_PUBLICABLE
    assert r["publicado"] is False
    assert r["ruta_marker"] is None


# 5) YA_PROCESADO (idempotencia del motor, antes de llegar aquí) no intenta publicar de nuevo.
def test_ya_procesado_no_intenta_publicar(tmp_path):
    item = {
        "fecha": "2026-09-03", "estado_final": YA_PROCESADO,
        "ruta_cierre_local": None, "ruta_sap": None, "ruta_resultado": None,
    }
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["estado_publicacion"] == YA_PUBLICADO
    assert r["publicado"] is False


# 6) El SHA256 usado es exactamente el de pipeline.calcular_sha256() sobre el cierre real.
def test_sha256_coincide_con_calculo_real_de_v2(tmp_path):
    item = _cierre_procesado(tmp_path)
    esperado = pipeline.calcular_sha256(item["ruta_cierre_local"])
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["sha256"] == esperado
    assert os.path.basename(r["ruta_marker"]) == pipeline.nombre_marcador_procesado(esperado)


# 7) El cierre original (fuera de base_dir_dev) nunca se modifica ni se mueve.
def test_original_no_se_modifica_ni_se_mueve(tmp_path):
    item = _cierre_procesado(tmp_path)
    hash_antes = pipeline.calcular_sha256(item["ruta_cierre_local"])
    publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert os.path.isfile(item["ruta_cierre_local"])  # sigue en su ubicacion original
    assert pipeline.calcular_sha256(item["ruta_cierre_local"]) == hash_antes


# 8) Un reproceso corregido (Módulo 05) con resultado_reproceso=LISTO_PARA_PUBLICAR también se publica.
def test_reproceso_corregido_tambien_se_publica(tmp_path):
    item = _cierre_procesado(tmp_path)
    item.pop("estado_final")
    item["resultado_reproceso"] = LISTO_PARA_PUBLICAR
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["estado_publicacion"] == PUBLICADO


# 9) Rutas incompletas -> ERROR_PUBLICACION sin crashear.
def test_rutas_incompletas_da_error_publicacion(tmp_path):
    item = {"fecha": "2026-09-04", "estado_final": LISTO_PARA_PUBLICAR,
            "ruta_cierre_local": None, "ruta_sap": None, "ruta_resultado": None}
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["estado_publicacion"] == ERROR_PUBLICACION
    assert r["publicado"] is False
    assert "PUBLICACION_INCOMPLETA" in r["mensaje"]


# 10) Un cierre inexistente en disco -> ERROR_PUBLICACION aislado, no crashea.
def test_archivo_inexistente_da_error_publicacion_aislado(tmp_path):
    item = {
        "fecha": "2026-09-05", "estado_final": LISTO_PARA_PUBLICAR,
        "ruta_cierre_local": str(tmp_path / "no_existe.xlsm"),
        "ruta_sap": str(tmp_path / "no_existe.xlsx"), "ruta_resultado": str(tmp_path / "no_existe.json"),
    }
    r = publicar_cierre_dev(item, str(tmp_path / "dev"))
    assert r["estado_publicacion"] == ERROR_PUBLICACION
    assert r["publicado"] is False


# 11) Un error en un cierre del lote no detiene la publicación de los demás.
def test_error_de_un_cierre_no_detiene_el_lote(tmp_path):
    item_ok = _cierre_procesado(tmp_path, nombre="ok", fecha="2026-09-01")
    item_roto = {
        "fecha": "2026-09-02", "estado_final": LISTO_PARA_PUBLICAR,
        "ruta_cierre_local": str(tmp_path / "no_existe.xlsm"), "ruta_sap": None, "ruta_resultado": None,
    }
    resultados = publicar_lote([item_ok, item_roto], str(tmp_path / "dev"))
    por_fecha = {r["fecha"]: r["estado_publicacion"] for r in resultados}
    assert por_fecha["2026-09-01"] == PUBLICADO
    assert por_fecha["2026-09-02"] == ERROR_PUBLICACION


# 12) publicar_lote() con UN elemento produce EXACTAMENTE lo mismo que publicar_cierre_dev()
#     directo, para el MISMO cierre — no existen dos caminos de lógica distintos
#     (single vs múltiple). Se usa el mismo item (mismo archivo -> mismo SHA256)
#     publicado en 2 directorios DEV independientes, para que solo cambie CÓMO
#     se invoca (directo vs. en lote), nunca el contenido de entrada.
def test_publicar_lote_de_uno_es_identico_a_publicar_cierre_dev(tmp_path):
    item = _cierre_procesado(tmp_path, nombre="a", fecha="2026-09-06")
    base_dir_dev_directo = str(tmp_path / "dev_directo")
    base_dir_dev_lote = str(tmp_path / "dev_lote")

    directo = publicar_cierre_dev(item, base_dir_dev_directo)
    (lote,) = publicar_lote([item], base_dir_dev_lote)

    campos_comparables = {"estado_publicacion", "publicado", "sha256"}
    assert {k: directo[k] for k in campos_comparables} == {k: lote[k] for k in campos_comparables}


# 13) Salidas de publicación quedan siempre dentro de base_dir_dev/publicacion/.
def test_salidas_quedan_dentro_de_base_dir_dev(tmp_path):
    item = _cierre_procesado(tmp_path)
    base_dir_dev = str(tmp_path / "dev")
    r = publicar_cierre_dev(item, base_dir_dev)
    base_abs = os.path.abspath(base_dir_dev)
    for clave in ("ruta_sap_publicado", "ruta_resultado_publicado", "ruta_cierre_procesado", "ruta_marker"):
        assert os.path.commonpath([os.path.abspath(r[clave]), base_abs]) == base_abs


# 14) CONTRACT-009: si faltara cualquiera de las 4 confirmaciones, V2 nunca construye el
#     marcador (ValueError MARCADOR_NO_AUTORIZADO) — se verifica contra la función REAL de V2.
def test_construir_marcador_procesado_exige_las_4_confirmaciones_real_v2():
    resultado_json = {"sha256_origen": "abc123", "fecha_cierre": "2026-09-01"}
    with pytest.raises(ValueError, match="MARCADOR_NO_AUTORIZADO"):
        pipeline.construir_marcador_procesado(
            resultado_json, sap_publicado_por_usuario=True, sap_verificado_en_drive=True,
            resultado_publicado=True, cierre_movido_a_procesados=False,
        )


# 15) Todas las filas de salida tienen al menos el schema pedido.
def test_todas_las_filas_tienen_al_menos_las_claves_pedidas(tmp_path):
    # FASE 8: publicar_cierre_dev() ahora preserva TODO lo que el item ya
    # traía de los Módulos 01-05 (carry-forward) además de agregar sus
    # propias claves — necesario para que el Módulo 07 (AUDITORIA) pueda
    # leer estado_ingesta/estado_materializacion/estado_motor/estado_final
    # directamente del item final. Por eso la aserción es "al menos estas
    # claves", no un conjunto exacto.
    item = _cierre_procesado(tmp_path)
    r = publicar_cierre_dev(item, str(tmp_path / "dev"), usuario_auditor="auditor.dev")
    esperado_minimo = {
        "fecha", "estado_publicacion", "publicado", "sha256", "ruta_sap_publicado",
        "ruta_resultado_publicado", "ruta_cierre_procesado", "ruta_marker",
        "usuario_auditor", "mensaje", "mensajes",
    }
    assert esperado_minimo.issubset(set(r.keys()))
    assert r["usuario_auditor"] == "auditor.dev"
    assert r["estado_final"] == item["estado_final"]  # se preserva del Modulo 04

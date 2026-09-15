"""tests_v3/test_dev_api.py — pruebas del backend DEV (v3/dev_api.py,
FASE 9) que conecta n8n_frontend/v3_control_cierres.html con los 7
módulos v3.* ya construidos. Verifica el CONTRATO de lotes (procesar →
estado → datos → revisar → corregir → publicar) end-to-end con archivos
reales, sin ningún mock del motor ni de las reglas contables.

Uso: python -m pytest tests_v3/test_dev_api.py -q
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

import xlsx_fixtures as fx  # noqa: E402
import run_batch  # noqa: E402
from v3.clasificacion import LISTO_PARA_PUBLICAR, ERROR_REVISAR, SIN_ARCHIVO  # noqa: E402
from v3.publicacion import PUBLICADO, YA_PUBLICADO  # noqa: E402
from v3 import dev_api  # noqa: E402


_SFC_VACIO = {"total_movimiento": "0.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": []}


def _correccion(categoria, tipo, identificadores, campo_corregido, valor_autorizado, usuario_auditor="auditor.test"):
    return {
        "categoria": categoria, "tipo": tipo, "identificadores": identificadores,
        "campo_corregido": campo_corregido, "valor_original": None,
        "valor_autorizado": valor_autorizado, "motivo": "test dev_api", "usuario_auditor": usuario_auditor,
    }


def _preparar_origen(tmp_path, cierres_por_fecha):
    origen_dir = tmp_path / "origen_drive"
    origen_dir.mkdir()
    for fecha, (sfc101, sfc102) in cierres_por_fecha.items():
        nombre = run_batch.nombre_cierre_esperado(fecha)
        fx.crear_cierre(str(origen_dir / nombre), sfc101, sfc102)
    ruta_maestro = tmp_path / "MAESTRO.xlsm"
    # FASE 10C: el precheck de cobertura del maestro (v3.precheck_maestro)
    # ahora corre entre materializacion y motor -- estos tests no ejercitan
    # esa precondicion (prueban CI/vouchers/publicacion, no cobertura de
    # MACROS/ATC), asi que el maestro sintetico trae una fila DUMMY por
    # cada fecha bajo prueba, suficiente para que el precheck confirme
    # MAESTRO_APTO sin alterar ningun resultado contable real (montos
    # "0.00"/"0.01" que nunca calzan con datos reales de las pruebas).
    fechas = sorted(cierres_por_fecha.keys())
    macros_filas = [(fecha, "DUMMY-PRECHECK", "0.01") for fecha in fechas]
    atc_filas = [(fecha, "BANCO (NETO)", "999999999", "DUMMY PRECHECK", "0.00", "DUMMY") for fecha in fechas]
    fx.crear_maestro_unico(str(ruta_maestro), macros_filas=macros_filas, atc_filas=atc_filas)
    ruta_plantilla = tmp_path / "Plantilla.xlsx"
    fx.crear_plantilla_sap(str(ruta_plantilla))
    return str(origen_dir), str(ruta_maestro), str(ruta_plantilla)


def _procesar(tmp_path, fecha_inicio, fecha_fin, cierres_por_fecha, usuario_auditor="auditor.dev"):
    origen_dir, ruta_maestro, ruta_plantilla = _preparar_origen(tmp_path, cierres_por_fecha)
    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente(fecha_inicio, fecha_fin, usuario_auditor, base_dir_dev)
    assert r["estado_lote"] == dev_api.PROCESANDO
    lote = dev_api.procesar_lote(r["lote_id"], base_dir_dev, origen_dir, ruta_maestro, ruta_plantilla)
    return lote, base_dir_dev


# 1) procesar rango válido
def test_procesar_rango_valido(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    assert lote["estado_lote"] == dev_api.LISTO_LOTE
    assert len(lote["cierres"]) == 1
    assert lote["cierres"][0]["estado_final"] == LISTO_PARA_PUBLICAR

    estado = dev_api.obtener_estado(lote["lote_id"], base_dir_dev)
    assert estado["total_cierres"] == 1 and estado["listos"] == 1

    datos = dev_api.obtener_datos(lote["lote_id"], base_dir_dev)
    assert datos["cierres"][0]["fecha"] == "2026-09-01"


# 2) rango con SIN_ARCHIVO
def test_rango_con_sin_archivo(tmp_path):
    lote, _ = _procesar(tmp_path, "2026-09-01", "2026-09-02", {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    por_fecha = {c["fecha"]: c["estado_final"] for c in lote["cierres"]}
    assert por_fecha["2026-09-01"] == LISTO_PARA_PUBLICAR
    assert por_fecha["2026-09-02"] == SIN_ARCHIVO


# 3) cierre ERROR_REVISAR — detalle de revisión expone excepciones reales + campos corregibles reutilizados
def _cierre_ci_bloqueante_dict():
    return {
        "total_movimiento": "100.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "100.00", "cuenta": None, "asignacion": "REF1", "banco": "BNB"}],
    }


def test_cierre_error_revisar_expone_detalle_real(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    assert lote["cierres"][0]["estado_final"] == ERROR_REVISAR

    detalle = dev_api.obtener_detalle_revision(lote["lote_id"], "2026-09-01", base_dir_dev)
    assert detalle["estado_final"] == ERROR_REVISAR
    assert detalle["requiere_revision"] is True
    assert len(detalle["excepciones"]) >= 1
    assert detalle["excepciones"][0]["categoria"] == "COMUNICACION_INTERNA"
    # HALLAZGO 1 (prueba manual FASE 9): /revisar YA expone sfc/factura
    # como campos DIRECTOS de la excepcion (motor_tiquipaya._excepciones_ci),
    # no anidados bajo "identificadores" -- el bug real estaba en que el
    # frontend buscaba exc.identificadores (inexistente) en vez de leer
    # exc.sfc/exc.factura directamente. Este assert confirma que el dato
    # SIEMPRE estuvo disponible del lado del backend, sin cambios aqui.
    assert detalle["excepciones"][0]["sfc"] == "SFC101"
    assert detalle["excepciones"][0]["factura"] == "F-1"
    # campos_corregibles: MISMO contenido de correcciones_tiquipaya.py (nunca
    # retipeado), solo convertido de set a lista ordenada para ser JSON-serializable.
    import correcciones_tiquipaya as correcciones
    esperado = {cat: sorted(campos) for cat, campos in correcciones.CAMPOS_CORREGIBLES.items()}
    assert detalle["campos_corregibles"] == esperado


# AJUSTE UX (prueba manual): dos filas CI bloqueantes SIMULTANEAS, una por
# cada tipo, para verificar que campos_corregibles_aplicables aisla el
# campo real de CADA excepcion — nunca ofrece el campo de la OTRA fila.
def _cierre_ci_asignacion_faltante_dict():
    return {
        "total_movimiento": "100.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [{"n": 1, "factura": "F-1", "total": "100.00", "cuenta": "210201005", "asignacion": None, "banco": "BNB"}],
    }


def _cierre_ci_dos_bloqueantes_dict():
    return {
        "total_movimiento": "200.00", "cobros_atc": "0.00", "dolares": "0.00", "depositos": [],
        "ci": [
            {"n": 1, "factura": "F-1", "total": "100.00", "cuenta": "210201005", "asignacion": None, "banco": "BNB"},
            {"n": 2, "factura": "F-2", "total": "100.00", "cuenta": None, "asignacion": "REF2", "banco": "BNB"},
        ],
    }


# UX-1) CI con problema SOLO de asignacion (cuenta_contable ya presente) ->
#       campos_corregibles_aplicables debe ofrecer UNICAMENTE "asignacion".
def test_campos_aplicables_ci_solo_asignacion(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_asignacion_faltante_dict(), _SFC_VACIO)})
    assert lote["cierres"][0]["estado_final"] == ERROR_REVISAR

    detalle = dev_api.obtener_detalle_revision(lote["lote_id"], "2026-09-01", base_dir_dev)
    assert len(detalle["excepciones"]) == 1
    exc = detalle["excepciones"][0]
    assert exc["tipo"] == "CI_ASIGNACION_FALTANTE"
    assert exc["campos_corregibles_aplicables"] == ["asignacion"]


# UX-2) Dos excepciones CI simultaneas (una de asignacion, otra de
#       cuenta_contable): cada una debe aislar SOLO su propio campo real.
#       Tras corregir la de asignacion, la que queda (cuenta_contable) debe
#       seguir ofreciendo UNICAMENTE cuenta_contable -- nunca "asignacion"
#       de la fila ya resuelta.
def test_campos_aplicables_tras_corregir_asignacion_queda_solo_cuenta(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_dos_bloqueantes_dict(), _SFC_VACIO)})
    assert lote["cierres"][0]["estado_final"] == ERROR_REVISAR

    detalle_inicial = dev_api.obtener_detalle_revision(lote["lote_id"], "2026-09-01", base_dir_dev)
    assert len(detalle_inicial["excepciones"]) == 2
    por_tipo = {exc["tipo"]: exc for exc in detalle_inicial["excepciones"]}
    assert por_tipo["CI_ASIGNACION_FALTANTE"]["campos_corregibles_aplicables"] == ["asignacion"]
    assert por_tipo["CI_CUENTA_FALTANTE"]["campos_corregibles_aplicables"] == ["cuenta_contable"]

    correccion = _correccion("COMUNICACION_INTERNA", "CI_ASIGNACION_FALTANTE", {"sfc": "SFC101", "factura": "F-1"}, "asignacion", "REF1")
    resultado = dev_api.aplicar_correccion(lote["lote_id"], "2026-09-01", correccion, base_dir_dev)
    assert resultado["correccion_aplicada"] is True
    assert resultado["resultado_reproceso"] == ERROR_REVISAR  # aun queda F-2 (cuenta_contable)

    detalle_final = dev_api.obtener_detalle_revision(lote["lote_id"], "2026-09-01", base_dir_dev)
    assert len(detalle_final["excepciones"]) == 1
    exc_final = detalle_final["excepciones"][0]
    assert exc_final["tipo"] == "CI_CUENTA_FALTANTE"
    assert exc_final["factura"] == "F-2"
    # UX-3: el campo ya corregido (asignacion, de F-1) no reaparece: F-1 ya
    # no genera ninguna excepcion, y la unica que queda (F-2) solo ofrece
    # cuenta_contable, nunca asignacion.
    assert exc_final["campos_corregibles_aplicables"] == ["cuenta_contable"]


# UX-4) Si el motor SIGUE reportando legitimamente el mismo problema tras un
#       reproceso (correccion aplicada a una fila que no era la bloqueante
#       real, o motor vuelve a encontrar el mismo campo vacio), el campo
#       puede volver a aparecer -- no hay "memoria" que lo excluya para
#       siempre, se recalcula fresco cada vez desde la excepcion real.
def test_campos_aplicables_reaparece_si_motor_lo_reporta_de_nuevo(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    detalle1 = dev_api.obtener_detalle_revision(lote["lote_id"], "2026-09-01", base_dir_dev)
    assert detalle1["excepciones"][0]["campos_corregibles_aplicables"] == ["cuenta_contable"]

    # Corrige con un valor vacio/invalido para cuenta_contable: la validacion
    # de esquema (correcciones_tiquipaya) exige un valor no vacio, asi que la
    # correccion es rechazada y la excepcion sigue intacta -- el campo sigue
    # apareciendo porque el motor sigue reportando el MISMO problema real.
    correccion_valida = _correccion("COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE", {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    resultado = dev_api.aplicar_correccion(lote["lote_id"], "2026-09-01", correccion_valida, base_dir_dev)
    assert resultado["correccion_aplicada"] is True
    assert resultado["resultado_reproceso"] == LISTO_PARA_PUBLICAR

    # Segundo cierre distinto con la MISMA excepcion real (misma fila
    # original, aun no corregida): el campo cuenta_contable reaparece
    # exactamente igual, calculado fresco desde la excepcion real de ESE
    # cierre -- no hay estado global que lo "recuerde" excluido.
    otro_tmp = tmp_path / "otro"
    otro_tmp.mkdir()
    lote2, base_dir_dev2 = _procesar(otro_tmp, "2026-09-02", "2026-09-02", {"2026-09-02": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    detalle2 = dev_api.obtener_detalle_revision(lote2["lote_id"], "2026-09-02", base_dir_dev2)
    assert detalle2["excepciones"][0]["campos_corregibles_aplicables"] == ["cuenta_contable"]


# UX-5) importe NUNCA debe ofrecerse como campo corregible, ni en
#       campos_corregibles (limites V2 por categoria) ni en
#       campos_corregibles_aplicables (subconjunto por excepcion puntual).
def test_campos_aplicables_nunca_ofrece_importe(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_dos_bloqueantes_dict(), _SFC_VACIO)})
    detalle = dev_api.obtener_detalle_revision(lote["lote_id"], "2026-09-01", base_dir_dev)
    for campos in detalle["campos_corregibles"].values():
        assert "importe" not in campos
    for exc in detalle["excepciones"]:
        assert "importe" not in exc["campos_corregibles_aplicables"]


# HALLAZGO 1 (prueba manual FASE 9): si (por un bug futuro del frontend o
# de cualquier otro cliente) una corrección llegara SIN identificadores
# reales, el backend debe seguir rechazándola exactamente igual que antes
# -- correcciones_tiquipaya.validar_schema_correccion()/_localizar_ci() no
# se relajan ni se tocan.
def test_correccion_sin_identificadores_reales_sigue_rechazada(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    correccion_sin_identificadores = _correccion("COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE", {}, "cuenta_contable", "210201005")
    resultado = dev_api.aplicar_correccion(lote["lote_id"], "2026-09-01", correccion_sin_identificadores, base_dir_dev)
    assert resultado["correccion_aplicada"] is False
    assert "CORRECCION_IDENTIFICADORES_INVALIDOS" in resultado["mensaje"]


# 4) corrección válida -> reproceso -> LISTO_PARA_PUBLICAR
def test_correccion_valida_reprocesa_a_listo(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    correccion = _correccion("COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE", {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")

    resultado = dev_api.aplicar_correccion(lote["lote_id"], "2026-09-01", correccion, base_dir_dev)
    assert resultado["correccion_aplicada"] is True
    assert resultado["resultado_reproceso"] == LISTO_PARA_PUBLICAR
    # el sha256_origen/version_correccion los calculo YO (dev_api), nunca el navegador
    assert "sha256_origen" not in correccion  # el dict original del "frontend" nunca lo tuvo

    datos = dev_api.obtener_datos(lote["lote_id"], base_dir_dev)
    assert datos["cierres"][0]["resultado_reproceso"] == LISTO_PARA_PUBLICAR


# 5) corrección de importe rechazada
def test_correccion_de_importe_rechazada(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    correccion = _correccion("COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE", {"sfc": "SFC101", "factura": "F-1"}, "importe", "999.00")

    resultado = dev_api.aplicar_correccion(lote["lote_id"], "2026-09-01", correccion, base_dir_dev)
    assert resultado["correccion_aplicada"] is False
    assert resultado["correccion_valida"] is False
    assert "CORRECCION_CAMPO_NO_CORREGIBLE" in resultado["mensaje"]


# 6) publicación válida
def test_publicacion_valida(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    r = dev_api.publicar_seleccionados(lote["lote_id"], ["2026-09-01"], base_dir_dev, "auditor.dev")
    assert len(r["publicados"]) == 1
    assert r["publicados"][0]["estado_publicacion"] == PUBLICADO
    assert r["omitidos"] == []
    assert os.path.isfile(r["ruta_auditoria_lote"])


# 7) publicación repetida idempotente
def test_publicacion_repetida_idempotente(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-01", {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    r1 = dev_api.publicar_seleccionados(lote["lote_id"], ["2026-09-01"], base_dir_dev, "auditor.dev")
    assert r1["publicados"][0]["estado_publicacion"] == PUBLICADO
    mtime_marker = os.path.getmtime(r1["publicados"][0]["ruta_marker"])

    r2 = dev_api.publicar_seleccionados(lote["lote_id"], ["2026-09-01"], base_dir_dev, "auditor.dev")
    assert r2["publicados"][0]["estado_publicacion"] == YA_PUBLICADO
    assert os.path.getmtime(r2["publicados"][0]["ruta_marker"]) == mtime_marker


# 8) error backend mostrado correctamente (lote inexistente)
def test_error_lote_no_encontrado():
    with pytest.raises(dev_api.LoteNoEncontradoError):
        dev_api.obtener_datos("no-existe-1234", "/tmp/no-importa")


# 9) (equivalente backend) frontend no permite publicar cierre no habilitado ->
#    el backend, autoridad final, rechaza/omite cualquier intento igual.
def test_backend_omite_publicacion_de_cierre_no_habilitado(tmp_path):
    lote, base_dir_dev = _procesar(tmp_path, "2026-09-01", "2026-09-02", {"2026-09-01": (_SFC_VACIO, _SFC_VACIO)})
    # 2026-09-02 quedo SIN_ARCHIVO: pedir publicarlo igual nunca debe publicar nada.
    r = dev_api.publicar_seleccionados(lote["lote_id"], ["2026-09-01", "2026-09-02"], base_dir_dev, "auditor.dev")
    publicados_fechas = {p["fecha"] for p in r["publicados"]}
    assert publicados_fechas == {"2026-09-01"}
    assert any(o["fecha"] == "2026-09-02" for o in r["omitidos"])


# 10) lote mixto: correccion + publicacion conviven sin contaminarse (aislamiento)
def test_lote_mixto_correccion_y_publicacion_aisladas(tmp_path):
    origen_dir, ruta_maestro, ruta_plantilla = _preparar_origen(tmp_path, {
        "2026-09-01": (_SFC_VACIO, _SFC_VACIO),
        "2026-09-02": (_cierre_ci_bloqueante_dict(), _SFC_VACIO),
    })
    base_dir_dev = str(tmp_path / "dev")
    r = dev_api.crear_lote_pendiente("2026-09-01", "2026-09-02", "auditor.dev", base_dir_dev)
    lote = dev_api.procesar_lote(r["lote_id"], base_dir_dev, origen_dir, ruta_maestro, ruta_plantilla)

    correccion = _correccion("COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE", {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    dev_api.aplicar_correccion(lote["lote_id"], "2026-09-02", correccion, base_dir_dev)

    pub = dev_api.publicar_seleccionados(lote["lote_id"], ["2026-09-01", "2026-09-02"], base_dir_dev, "auditor.dev")
    publicados_fechas = {p["fecha"]: p["estado_publicacion"] for p in pub["publicados"]}
    assert publicados_fechas == {"2026-09-01": PUBLICADO, "2026-09-02": PUBLICADO}
    assert pub["omitidos"] == []


# 11) CLI real (main()) para las 7 acciones: nunca deja un output.json
#     truncado/no-serializable en disco. Este es EXACTAMENTE el tipo de bug
#     que ningun test anterior detecta (llaman las funciones Python directo,
#     nunca pasan por json.dump) pero que rompe el webhook real de n8n --
#     CAMPOS_CORREGIBLES son sets en Python y json.dump() no los serializa
#     tal cual; se detecto ejecutando el workflow real (FASE 9).
def test_cli_main_produce_json_valido_para_todas_las_acciones(tmp_path):
    origen_dir, ruta_maestro, ruta_plantilla = _preparar_origen(tmp_path, {"2026-09-01": (_cierre_ci_bloqueante_dict(), _SFC_VACIO)})
    base_dir_dev = str(tmp_path / "dev")

    def _run(accion, payload):
        ruta_in = tmp_path / f"in_{accion}.json"
        ruta_out = tmp_path / f"out_{accion}.json"
        ruta_in.write_text(json.dumps(payload), encoding="utf-8")
        dev_api.main(["--accion", accion, "--input", str(ruta_in), "--output", str(ruta_out)])
        with open(ruta_out, "r", encoding="utf-8") as f:
            return json.load(f)  # lanza si el archivo quedo truncado/invalido

    r1 = _run("crear_lote_pendiente", {"fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-01", "usuario_auditor": "a", "base_dir_dev": base_dir_dev})
    assert r1["resultado"] == "OK"
    lote_id = r1["lote_id"]

    r2 = _run("procesar_lote", {"lote_id": lote_id, "base_dir_dev": base_dir_dev, "origen_cierres_dir": origen_dir, "ruta_maestro_origen": ruta_maestro, "ruta_plantilla_origen": ruta_plantilla})
    assert r2["resultado"] == "OK" and r2["estado_lote"] == dev_api.LISTO_LOTE

    r3 = _run("estado", {"lote_id": lote_id, "base_dir_dev": base_dir_dev})
    assert r3["resultado"] == "OK"

    r4 = _run("datos", {"lote_id": lote_id, "base_dir_dev": base_dir_dev})
    assert r4["resultado"] == "OK" and len(r4["cierres"]) == 1

    r5 = _run("revisar", {"lote_id": lote_id, "fecha": "2026-09-01", "base_dir_dev": base_dir_dev})
    assert r5["resultado"] == "OK"
    assert r5["campos_corregibles"]["COMUNICACION_INTERNA"] == sorted(["cuenta_contable", "asignacion"])

    correccion = _correccion("COMUNICACION_INTERNA", "CI_CUENTA_FALTANTE", {"sfc": "SFC101", "factura": "F-1"}, "cuenta_contable", "210201005")
    r6 = _run("corregir", {"lote_id": lote_id, "fecha": "2026-09-01", "correccion": correccion, "base_dir_dev": base_dir_dev})
    assert r6["resultado"] == "OK" and r6["cierre"]["resultado_reproceso"] == LISTO_PARA_PUBLICAR

    r7 = _run("publicar", {"lote_id": lote_id, "fechas": ["2026-09-01"], "usuario_auditor": "a", "base_dir_dev": base_dir_dev})
    assert r7["resultado"] == "OK" and r7["publicados"][0]["estado_publicacion"] == PUBLICADO

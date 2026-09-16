"""Tests del motor de matching Cochabamba vs BCP."""

import datetime as dt
import os
import sys

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matcher as M

CFG = M.Config()


# --------------------------------------------------------------------------- #
# Fabricas de datos
# --------------------------------------------------------------------------- #

def reg(fila, fecha_hora, monto, es_qr=True, estudiante="ALUMNO PRUEBA", factura="1"):
    return M.RegistroCBB(
        fila_excel=fila,
        crudo={"Nro": fila, "Numero Factura": factura, "Nombre Estudiante": estudiante,
               "Monto": monto, "Fecha": fecha_hora, "Tipo Pago": "QR" if es_qr else "Tarjeta D/C"},
        fecha_hora=fecha_hora,
        centavos=M.a_centavos(monto),
        es_qr=es_qr,
    )


def mov(fila, fecha_hora, importe, oper, glosa="QR DE PRUEBA", cd=None):
    return M.MovimientoBCP(
        fila_excel=fila,
        crudo={},
        fecha_hora=fecha_hora,
        centavos=M.a_centavos(importe),
        nro_oper=oper,
        nro_oper_norm=M.norm_id(oper),
        glosa=glosa,
        cd_confirmacion=cd,
        es_qr="QR" in glosa.upper(),
    )


def t(h, m, s=0, dia=1):
    return dt.datetime(2026, 9, dia, h, m, s)


# --------------------------------------------------------------------------- #
# 1-2. Coincidencia exacta y de 1 segundo
# --------------------------------------------------------------------------- #

def test_coincidencia_exacta():
    res = M.emparejar([reg(1, t(10, 49, 11), 2630)], [mov(2, t(10, 49, 11), 2630, 301902)], CFG)
    assert len(res) == 1
    assert res[0].estado == M.ESTADO_SEGURO
    assert res[0].diferencia_seg == 0
    assert res[0].movimiento.nro_oper == 301902


def test_diferencia_de_un_segundo():
    res = M.emparejar([reg(1, t(10, 49, 11), 2630)], [mov(2, t(10, 49, 10), 2630, 301902)], CFG)
    assert res[0].estado == M.ESTADO_SEGURO
    assert res[0].diferencia_seg == 1.0


# --------------------------------------------------------------------------- #
# 3-4. Mismo monto repetido el mismo dia, asignado 1 a 1 por hora
# --------------------------------------------------------------------------- #

def test_mismo_monto_repetido_elige_el_mas_cercano():
    registros = [reg(1, t(10, 0, 0), 500)]
    movimientos = [mov(2, t(10, 0, 40), 500, "A"), mov(3, t(10, 0, 1), 500, "B")]
    res = M.emparejar(registros, movimientos, CFG)
    assert res[0].movimiento.nro_oper == "B"
    assert res[0].diferencia_seg == 1.0
    assert res[0].candidatos == 2


def test_asignacion_uno_a_uno_por_hora():
    registros = [reg(1, t(10, 0, 0), 500), reg(2, t(10, 5, 0), 500)]
    movimientos = [mov(10, t(10, 5, 1), 500, "TARDE"), mov(11, t(10, 0, 1), 500, "TEMPRANO")]
    res = M.emparejar(registros, movimientos, CFG)
    asignado = {r.registro.fila_excel: r.movimiento.nro_oper for r in res}
    assert asignado == {1: "TEMPRANO", 2: "TARDE"}
    assert all(r.diferencia_seg == 1.0 for r in res)


def test_asignacion_global_minima_no_solo_el_primero():
    # Si se tomara "el primero que aparece", el registro 1 robaria el movimiento
    # del registro 2 y este quedaria mal emparejado.
    registros = [reg(1, t(10, 0, 0), 800), reg(2, t(10, 0, 4), 800)]
    movimientos = [mov(10, t(10, 0, 3), 800, "X"), mov(11, t(10, 0, 0), 800, "Y")]
    res = M.emparejar(registros, movimientos, CFG)
    asignado = {r.registro.fila_excel: r.movimiento.nro_oper for r in res}
    assert asignado == {1: "Y", 2: "X"}


# --------------------------------------------------------------------------- #
# 5. Un movimiento BCP no puede usarse dos veces
# --------------------------------------------------------------------------- #

def test_bcp_nunca_se_reutiliza():
    registros = [reg(1, t(10, 0, 0), 500), reg(2, t(10, 0, 2), 500)]
    movimientos = [mov(10, t(10, 0, 1), 500, 777)]
    res = M.emparejar(registros, movimientos, CFG)
    usados = [r.movimiento.nro_oper for r in res if r.movimiento]
    assert usados == [777]
    sin_match = [r for r in res if r.movimiento is None]
    assert len(sin_match) == 1
    assert sin_match[0].estado == M.ESTADO_SIN_MATCH
    assert "ya asignados" in sin_match[0].motivo


# --------------------------------------------------------------------------- #
# 6-7. Sin candidato y candidato fuera de la ventana
# --------------------------------------------------------------------------- #

def test_sin_candidato():
    res = M.emparejar([reg(1, t(10, 0, 0), 500)], [mov(10, t(10, 0, 0), 999, 1)], CFG)
    assert res[0].estado == M.ESTADO_SIN_MATCH
    assert res[0].movimiento is None
    assert res[0].candidatos == 0


def test_candidato_fuera_de_ventana_no_se_asigna():
    res = M.emparejar([reg(1, t(10, 0, 0), 500)], [mov(10, t(10, 3, 0), 500, 1)], CFG)
    assert res[0].estado == M.ESTADO_SIN_MATCH
    assert res[0].movimiento is None
    assert "180 s" in res[0].motivo  # informa el mas cercano sin asignarlo


def test_escalera_de_umbrales():
    casos = {3: M.ESTADO_SEGURO, 20: M.ESTADO_PROBABLE, 100: M.ESTADO_REVISAR, 200: M.ESTADO_SIN_MATCH}
    for segundos, esperado in casos.items():
        res = M.emparejar(
            [reg(1, t(10, 0, 0), 500)],
            [mov(10, t(10, 0, 0) + dt.timedelta(seconds=segundos), 500, 1)],
            CFG,
        )
        assert res[0].estado == esperado, f"{segundos} s deberia ser {esperado}"


# --------------------------------------------------------------------------- #
# 8. Cd. Confirmacion de otra ciudad no invalida el match
# --------------------------------------------------------------------------- #

def test_cd_confirmacion_sucre_no_impide_el_match():
    res = M.emparejar(
        [reg(1, t(11, 38, 56), 660)],
        [mov(10, t(11, 38, 55), 660, 364703, cd="SUCRE")],
        CFG,
    )
    assert res[0].estado == M.ESTADO_SEGURO
    assert res[0].movimiento.nro_oper == 364703
    assert M._conflicto_ciudad(res[0], CFG) is True
    # El valor original se muestra tal cual, nunca se reemplaza.
    fila = M.a_filas(res, CFG)[0]
    assert fila["BCP_Cd_Confirmacion"] == "SUCRE"
    assert fila["Conflicto_Ciudad"] == "SI"
    assert fila["Estado_match"] == M.ESTADO_SEGURO


# --------------------------------------------------------------------------- #
# 9. Nro Oper. duplicado en BCP genera alerta
# --------------------------------------------------------------------------- #

def test_nro_oper_duplicado_genera_alerta():
    movimientos = [mov(10, t(10, 0, 0), 500, 301902), mov(11, t(12, 0, 0), 900, "301902")]
    alertas = M.validar([], movimientos, [], CFG)
    detalles = [d for _, d, _ in alertas]
    assert any("Nro Oper. duplicados" in d for d in detalles)
    assert any("301902" in d for d in detalles)


def test_nro_oper_normalizado():
    assert M.norm_id(301902) == "301902"
    assert M.norm_id("301902") == "301902"
    assert M.norm_id(" 301902 ") == "301902"
    assert M.norm_id(301902.0) == "301902"
    assert M.norm_id("301902.0") == "301902"


# --------------------------------------------------------------------------- #
# 10. Una celda "Fecha" suelta arriba del reporte no confunde al detector
# --------------------------------------------------------------------------- #

def _crear_cbb(ruta, con_membrete=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RPagosEnLinea"
    if con_membrete:
        ws.cell(row=3, column=24, value="Fecha:")
        ws.cell(row=3, column=32, value="16/09/2026 15:48")
        ws.cell(row=6, column=11, value="INGRESO DIARIO")
        ws.cell(row=10, column=7, value="SEDE COCHABAMBA")
    fila = 13
    encabezados = ["Nro", "Fecha", "Número Factura", "Nit/C.I.", "Razon Social",
                   "Nombre Estudiante", "Tipo Pago", "Monto", "Canal de Pago", "Estado"]
    for c, nombre in enumerate(encabezados, start=1):
        ws.cell(row=fila, column=c, value=nombre)
    datos = [
        (1, dt.datetime(2026, 9, 1, 10, 49, 11), "16180", "7863318", "GARRON",
         "GARRON CESPEDES AYRIN", "QR", 2630, "Pago En Línea", "Válido"),
        (2, dt.datetime(2026, 9, 1, 11, 0, 0), "16181", "123", "X",
         "OTRO ALUMNO", "Tarjeta D/C", 151, "Pago En Línea", "Válido"),
    ]
    for i, registro in enumerate(datos, start=fila + 1):
        for c, valor in enumerate(registro, start=1):
            ws.cell(row=i, column=c, value=valor)
    ws.cell(row=fila + 4, column=2, value="Monto QR:")
    ws.cell(row=fila + 4, column=6, value="2,630.00")
    wb.save(ruta)


def _crear_bcp(ruta):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    encabezados = ["Fecha", "Hora", "Glosa", "Tipo", "Suc. Age.", "Usuario",
                   "Importe", "Saldo", "Nro Oper. cod. Bancarizacion", "Cd, Confirmacion"]
    for c, nombre in enumerate(encabezados, start=1):
        ws.cell(row=1, column=c, value=nombre)
    datos = [
        (dt.datetime(2026, 9, 1), dt.time(10, 49, 10), "QR DE Garron Otalora", 2401,
         201204, "AK0", 2630, 5803394.75, 301902, None),
        (dt.datetime(2026, 9, 1), dt.time(11, 3, 25), "CHEQUE 00015925", 3001,
         301328, "HD1", -2532.6, 5814449.15, 70, None),
        (dt.datetime(2026, 9, 1), dt.time(11, 38, 55), "QR DE DONAIRE JONATH", 2401,
         201204, "AK0", 660, 5815711.15, 364703, "SUCRE"),
    ]
    for i, registro in enumerate(datos, start=2):
        for c, valor in enumerate(registro, start=1):
            ws.cell(row=i, column=c, value=valor)
    wb.save(ruta)


def test_no_confunde_la_celda_fecha_del_membrete(tmp_path):
    ruta = tmp_path / "cbb.xlsx"
    _crear_cbb(ruta)
    hojas = M.leer_libro(str(ruta))
    fila = M.detectar_fila_encabezado(hojas[0][1], M.REQUERIDOS_CBB)
    assert fila == 12  # 0-based: fila 13 de Excel, no la fila 3 del membrete


def test_encabezado_requiere_todos_los_campos():
    filas = [["Fecha:", "16/09/2026 15:48"], ["Fecha", "Monto"]]
    assert M.detectar_fila_encabezado(filas, M.REQUERIDOS_CBB) is None


# --------------------------------------------------------------------------- #
# Identificacion de archivos y flujo completo
# --------------------------------------------------------------------------- #

def test_identifica_los_archivos_en_cualquier_orden(tmp_path):
    ruta_cbb, ruta_bcp = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _crear_cbb(ruta_cbb)
    _crear_bcp(ruta_bcp)
    for orden in ([str(ruta_cbb), str(ruta_bcp)], [str(ruta_bcp), str(ruta_cbb)]):
        cbb, bcp = M.identificar_tablas(orden)
        assert cbb.ruta == str(ruta_cbb) and cbb.hoja == "RPagosEnLinea"
        assert bcp.ruta == str(ruta_bcp) and bcp.hoja == "Hoja1"


def test_error_claro_si_falta_un_archivo(tmp_path):
    ruta_bcp = tmp_path / "b.xlsx"
    _crear_bcp(ruta_bcp)
    with pytest.raises(ValueError, match="No pude identificar ambas tablas"):
        M.identificar_tablas([str(ruta_bcp)])


def test_flujo_completo_no_modifica_los_originales(tmp_path):
    ruta_cbb, ruta_bcp = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _crear_cbb(ruta_cbb)
    _crear_bcp(ruta_bcp)
    antes = {r: (os.path.getsize(r), open(r, "rb").read()) for r in (ruta_cbb, ruta_bcp)}

    salida = tmp_path / "MATCH_CBB.xlsx"
    datos = M.ejecutar([str(ruta_cbb), str(ruta_bcp)], str(salida), CFG)

    assert {r: (os.path.getsize(r), open(r, "rb").read()) for r in (ruta_cbb, ruta_bcp)} == antes
    assert salida.exists()
    wb = openpyxl.load_workbook(salida)
    assert wb.sheetnames == ["RESUMEN", "COCHABAMBA_MATCH", "MATCH_SEGURO", "MATCH_PROBABLE",
                             "REVISAR", "SIN_MATCH", "NO_QR", "TODOS"]
    assert len(datos["registros"]) == 2  # el pie de totales no se cuenta como registro
    estados = {r.registro.crudo["Numero Factura"]: r.estado for r in datos["resultados"]}
    assert estados == {"16180": M.ESTADO_SEGURO, "16181": M.ESTADO_NO_QR}


def test_no_fuerza_tarjeta_contra_qr():
    registros = [reg(1, t(10, 0, 0), 500, es_qr=False)]
    movimientos = [mov(10, t(10, 0, 0), 500, 1)]
    res = M.emparejar(registros, movimientos, CFG)
    assert res[0].estado == M.ESTADO_NO_QR
    assert res[0].movimiento is None


def test_bcp_negativo_nunca_se_asigna():
    res = M.emparejar([reg(1, t(10, 0, 0), 500)], [mov(10, t(10, 0, 0), -500, 1, glosa="QR DEVOLUCION")], CFG)
    assert res[0].estado == M.ESTADO_SIN_MATCH


def test_movimiento_sin_qr_en_glosa_se_excluye():
    movimientos = [mov(10, t(10, 0, 0), 500, 1, glosa="CHEQUE 00015925")]
    assert M.emparejar([reg(1, t(10, 0, 0), 500)], movimientos, CFG)[0].movimiento is None
    sin_filtro = M.Config(solo_qr_bcp=False)
    assert M.emparejar([reg(1, t(10, 0, 0), 500)], movimientos, sin_filtro)[0].movimiento is not None


# --------------------------------------------------------------------------- #
# Ambiguedad
# --------------------------------------------------------------------------- #

def test_candidato_libre_cercano_degrada_a_revisar():
    registros = [reg(1, t(10, 10, 0), 500)]
    movimientos = [mov(10, t(10, 10, 2), 500, "A"), mov(11, t(10, 10, 3), 500, "B")]
    res = M.emparejar(registros, movimientos, CFG)
    assert res[0].movimiento.nro_oper == "A"
    assert res[0].diferencia_seg == 2.0
    assert res[0].segundo_delta == 3.0
    assert res[0].margen == 1.0
    assert res[0].ambiguo is True
    assert res[0].estado == M.ESTADO_REVISAR


def test_candidato_alternativo_ocupado_no_genera_ambiguedad():
    registros = [reg(1, t(10, 10, 0), 500), reg(2, t(10, 10, 5), 500)]
    movimientos = [mov(10, t(10, 10, 1), 500, "A"), mov(11, t(10, 10, 4), 500, "B")]
    res = M.emparejar(registros, movimientos, CFG)
    assert [r.estado for r in res] == [M.ESTADO_SEGURO, M.ESTADO_SEGURO]
    assert [r.ambiguo for r in res] == [False, False]


# --------------------------------------------------------------------------- #
# Conversiones
# --------------------------------------------------------------------------- #

def test_redondeo_de_segundo_elimina_el_desfase_del_serial():
    # 46266.450822997685 -> 10:49:11.107 en el reporte real de Cochabamba.
    crudo = M.a_datetime(46266.450822997685)
    assert crudo.microsecond != 0
    assert M.redondear_a_segundo(crudo) == dt.datetime(2026, 9, 1, 10, 49, 11)


def test_conversion_de_montos():
    assert M.a_centavos(2630) == 263000
    assert M.a_centavos(2630.5) == 263050
    assert M.a_centavos("2,630.50") == 263050
    assert M.a_centavos("633,334.97") == 63333497
    assert M.a_centavos("") is None
    assert M.a_centavos("abc") is None


def test_conversion_de_horas():
    assert M.a_time(dt.time(10, 49, 10)) == dt.time(10, 49, 10)
    assert M.a_time(dt.datetime(2026, 9, 1, 10, 49, 10)) == dt.time(10, 49, 10)
    assert M.a_time("10:49:10") == dt.time(10, 49, 10)
    assert M.a_time(0.45082) == dt.time(10, 49, 11)
    assert M.a_time(None) is None


def test_registro_sin_fecha_queda_incompleto():
    registro = M.RegistroCBB(5, {"Numero Factura": "1"}, None, 50000, True, ["FECHA_INVALIDA"])
    res = M.emparejar([registro], [mov(10, t(10, 0, 0), 500, 1)], CFG)
    assert res[0].estado == M.ESTADO_INCOMPLETO
    assert res[0].movimiento is None

"""Presentacion de MATCH_CBB.xlsx: la misma informacion, legible para una persona.

Este modulo solo da formato. No decide ningun match ni altera ningun resultado.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import matcher as M

# Paleta suave y consistente: (encabezado, relleno de fila)
VERDE = ("2E7D32", "E8F5E9")
AZUL = ("1565C0", "E3F2FD")
NARANJA = ("E65100", "FFF8E1")
ROJO = ("B71C1C", "FFEBEE")
ROJO_INTENSO = "FFCDD2"
GRIS = ("616161", "F5F5F5")
AZUL_OSCURO = ("1F4E79", "FFFFFF")
ROJO_TEXTO = "C62828"

COLOR_POR_ESTADO = {
    M.ESTADO_SEGURO: VERDE[1],
    M.ESTADO_PROBABLE: AZUL[1],
    M.ESTADO_REVISAR: NARANJA[1],
    M.ESTADO_SIN_MATCH: ROJO[1],
    M.ESTADO_INCOMPLETO: ROJO[1],
    M.ESTADO_NO_QR: GRIS[1],
}

FECHA_HORA = "DD/MM/YYYY HH:MM:SS"
MONEDA = "#,##0.00"
BORDE = Border(*(Side(style="thin", color="D0D0D0"),) * 4)

SIN_MATCH_CORTE = "SIN_MATCH_CORTE_BCP"
SIN_MATCH_REAL = "SIN_MATCH_REAL"

ETIQUETAS_ESTADISTICA = {
    "minimo": "Mínimo (seg)", "mediana": "Mediana (seg)", "p90": "Percentil 90 (seg)",
    "p95": "Percentil 95 (seg)", "maximo": "Máximo (seg)",
}


class Columna:
    """Una columna de una hoja operativa: titulo humano, valor y formato."""

    def __init__(self, titulo: str, valor: Callable[[Any], Any], formato: str | None = None, ancho: int | None = None):
        self.titulo = titulo
        self.valor = valor
        self.formato = formato
        self.ancho = ancho


# --------------------------------------------------------------------------- #
# Datos derivados (solo para mostrar)
# --------------------------------------------------------------------------- #

def _delta_con_signo(res: M.Resultado) -> float | None:
    """Positivo = la factura se emitio despues del abono bancario."""
    if res.movimiento is None or res.registro.fecha_hora is None or res.movimiento.fecha_hora is None:
        return None
    return round((res.registro.fecha_hora - res.movimiento.fecha_hora).total_seconds(), 3)


def _cd(res: M.Resultado) -> Any:
    return res.movimiento.cd_confirmacion if res.movimiento else None


def _observacion_pegar(res: M.Resultado) -> str:
    cd = str(_cd(res)).strip() if _cd(res) not in (None, "") else ""
    base = "Listo para usar" if res.estado == M.ESTADO_SEGURO else "Probable, conviene revisar"
    if cd:
        return f"{base} — ya tenía Cd. Confirmación ({cd})"
    return base


def _motivo_revision(res: M.Resultado) -> str:
    if res.motivo:
        return res.motivo
    if res.candidatos > 1:
        return f"{res.candidatos} movimientos BCP posibles en la misma fecha y monto"
    return f"Candidato único con diferencia de {res.diferencia_seg:.0f} s"


def _accion_sugerida(res: M.Resultado) -> str:
    if res.ambiguo or res.candidatos > 1:
        return "Revisar, más de un candidato posible"
    if res.diferencia_seg is not None and res.diferencia_seg > 30:
        return "Revisar manualmente, delta alto"
    return "Revisar, candidato único"


def _tipo_sin_match(res: M.Resultado, inicio: dt.datetime | None, fin: dt.datetime | None) -> str:
    """Distingue el pago que el extracto no alcanza a cubrir del que deberia estar y no esta."""
    fecha = res.registro.fecha_hora
    if fecha is None or inicio is None or fin is None:
        return SIN_MATCH_REAL
    return SIN_MATCH_CORTE if fecha > fin or fecha < inicio else SIN_MATCH_REAL


def _prioridad(res: M.Resultado, tipo_sin_match: str | None) -> str:
    if res.estado in (M.ESTADO_SIN_MATCH, M.ESTADO_INCOMPLETO):
        return "MEDIA" if tipo_sin_match == SIN_MATCH_CORTE else "ALTA"
    if res.estado == M.ESTADO_REVISAR:
        return "MEDIA"
    return "BAJA"


# --------------------------------------------------------------------------- #
# Escritura generica de hojas
# --------------------------------------------------------------------------- #

def _escribir_tabla(
    ws,
    columnas: Sequence[Columna],
    filas: Sequence[Any],
    *,
    encabezado: tuple[str, str],
    relleno: Callable[[Any], str | None] | None = None,
    fila_inicio: int = 1,
) -> None:
    fuente_encabezado = Font(bold=True, color="FFFFFF", size=11)
    relleno_encabezado = PatternFill("solid", fgColor=encabezado[0])

    for c, columna in enumerate(columnas, start=1):
        celda = ws.cell(row=fila_inicio, column=c, value=columna.titulo)
        celda.font = fuente_encabezado
        celda.fill = relleno_encabezado
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = BORDE

    for i, fila in enumerate(filas, start=fila_inicio + 1):
        color = relleno(fila) if relleno else None
        for c, columna in enumerate(columnas, start=1):
            celda = ws.cell(row=i, column=c, value=columna.valor(fila))
            celda.border = BORDE
            if columna.formato:
                celda.number_format = columna.formato
            if color:
                celda.fill = PatternFill("solid", fgColor=color)

    ws.freeze_panes = ws.cell(row=fila_inicio + 1, column=1)
    if filas:
        ws.auto_filter.ref = (
            f"A{fila_inicio}:{get_column_letter(len(columnas))}{fila_inicio + len(filas)}"
        )
    ws.row_dimensions[fila_inicio].height = 30
    _ajustar_anchos(ws, columnas, filas, fila_inicio)


def _ajustar_anchos(ws, columnas: Sequence[Columna], filas: Sequence[Any], fila_inicio: int) -> None:
    for c, columna in enumerate(columnas, start=1):
        if columna.ancho:
            ws.column_dimensions[get_column_letter(c)].width = columna.ancho
            continue
        largos = [len(columna.titulo)]
        for fila in filas[:400]:
            valor = columna.valor(fila)
            if isinstance(valor, dt.datetime):
                largos.append(19)
            elif valor is not None:
                largos.append(len(f"{valor:,.2f}") if columna.formato == MONEDA and isinstance(valor, (int, float))
                              else len(str(valor)))
        ws.column_dimensions[get_column_letter(c)].width = min(max(max(largos) + 2, 10), 42)


# --------------------------------------------------------------------------- #
# Hojas operativas
# --------------------------------------------------------------------------- #

def _columnas_comunes() -> list[Columna]:
    return [
        Columna("Factura", lambda r: r.registro.crudo.get("Numero Factura"), ancho=12),
        Columna("Nombre Estudiante", lambda r: r.registro.crudo.get("Nombre Estudiante")),
        Columna("Fecha y hora CBB", lambda r: r.registro.fecha_hora, FECHA_HORA, ancho=21),
        Columna("Monto Bs", lambda r: M.centavos_a_float(r.registro.centavos), MONEDA, ancho=13),
    ]


def _hoja_para_pegar(ws, resultados: Sequence[M.Resultado]) -> None:
    columnas = [
        Columna("Estado", lambda r: r.estado, ancho=16),
        *_columnas_comunes(),
        Columna("Tipo Pago", lambda r: r.registro.crudo.get("Tipo Pago"), ancho=12),
        Columna("Canal de Pago", lambda r: r.registro.crudo.get("Canal de Pago"), ancho=15),
        Columna("Fecha y hora BCP", lambda r: r.movimiento.fecha_hora if r.movimiento else None, FECHA_HORA, ancho=21),
        Columna("Dif. seg", lambda r: r.diferencia_seg, "0", ancho=9),
        Columna("Nro Oper BCP", lambda r: r.movimiento.nro_oper if r.movimiento else None, ancho=14),
        Columna("Glosa BCP", lambda r: r.movimiento.glosa.strip() if r.movimiento else None, ancho=24),
        Columna("Cd. Confirmación BCP", lambda r: _cd(r), ancho=18),
        Columna("Observación", _observacion_pegar, ancho=42),
    ]
    _escribir_tabla(ws, columnas, resultados, encabezado=AZUL_OSCURO,
                    relleno=lambda r: COLOR_POR_ESTADO.get(r.estado))


def _hoja_revisar(ws, resultados: Sequence[M.Resultado]) -> None:
    columnas = [
        *_columnas_comunes(),
        Columna("Fecha y hora BCP", lambda r: r.movimiento.fecha_hora if r.movimiento else None, FECHA_HORA, ancho=21),
        Columna("Dif. seg", lambda r: r.diferencia_seg, "0", ancho=9),
        Columna("Delta con signo", _delta_con_signo, "+0;-0;0", ancho=15),
        Columna("Nro Oper BCP", lambda r: r.movimiento.nro_oper if r.movimiento else None, ancho=14),
        Columna("Glosa BCP", lambda r: r.movimiento.glosa.strip() if r.movimiento else None, ancho=24),
        Columna("Cd. Confirmación BCP", lambda r: _cd(r), ancho=18),
        Columna("Candidatos", lambda r: r.candidatos, "0", ancho=11),
        Columna("2º mejor (seg)", lambda r: r.segundo_delta, "0", ancho=13),
        Columna("Margen vs 2º", lambda r: r.margen, "0", ancho=13),
        Columna("Motivo de revisión", _motivo_revision, ancho=40),
        Columna("Acción sugerida", _accion_sugerida, ancho=34),
    ]
    _escribir_tabla(ws, columnas, resultados, encabezado=NARANJA, relleno=lambda r: NARANJA[1])

    # Resaltar en rojo la diferencia cuando supera los 30 s.
    col_dif = next(i for i, c in enumerate(columnas, start=1) if c.titulo == "Dif. seg")
    for i, res in enumerate(resultados, start=2):
        if res.diferencia_seg is not None and res.diferencia_seg > 30:
            celda = ws.cell(row=i, column=col_dif)
            celda.font = Font(bold=True, color=ROJO_TEXTO)
            celda.fill = PatternFill("solid", fgColor=ROJO_INTENSO)


def _hoja_sin_match(ws, resultados: Sequence[M.Resultado], tipos: dict[int, str]) -> None:
    columnas = [
        *_columnas_comunes(),
        Columna("Tipo Pago", lambda r: r.registro.crudo.get("Tipo Pago"), ancho=12),
        Columna("Canal de Pago", lambda r: r.registro.crudo.get("Canal de Pago"), ancho=15),
        Columna("Tipo sin match", lambda r: tipos[r.registro.fila_excel], ancho=22),
        Columna("Candidato más cercano — fecha y hora",
                lambda r: r.candidato_cercano.fecha_hora if r.candidato_cercano else None, FECHA_HORA, ancho=21),
        Columna("Candidato más cercano — Nro Oper",
                lambda r: r.candidato_cercano.nro_oper if r.candidato_cercano else None, ancho=16),
        Columna("Candidato más cercano — Glosa",
                lambda r: r.candidato_cercano.glosa.strip() if r.candidato_cercano else None, ancho=24),
        Columna("Candidato más cercano — Dif. seg", lambda r: r.candidato_cercano_delta, "0", ancho=16),
        Columna("Motivo", lambda r: r.motivo, ancho=42),
    ]
    _escribir_tabla(ws, columnas, resultados, encabezado=ROJO,
                    relleno=lambda r: ROJO_INTENSO if tipos[r.registro.fila_excel] == SIN_MATCH_REAL else ROJO[1])


def _hoja_no_qr(ws, resultados: Sequence[M.Resultado]) -> None:
    columnas = [
        *_columnas_comunes(),
        Columna("Tipo Pago", lambda r: r.registro.crudo.get("Tipo Pago"), ancho=14),
        Columna("Canal de Pago", lambda r: r.registro.crudo.get("Canal de Pago"), ancho=15),
        Columna("Estado", lambda r: r.registro.crudo.get("Estado"), ancho=12),
        Columna("Observación", lambda r: "No incluido en cruce QR", ancho=28),
    ]
    _escribir_tabla(ws, columnas, resultados, encabezado=GRIS, relleno=lambda r: GRIS[1])


def _hoja_auditoria(ws, resultados: Sequence[M.Resultado], tipos: dict[int, str]) -> None:
    orden = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
    filas = sorted(
        resultados,
        key=lambda r: (orden[_prioridad(r, tipos.get(r.registro.fila_excel))], r.registro.fila_excel),
    )
    columnas = [
        Columna("Prioridad", lambda r: _prioridad(r, tipos.get(r.registro.fila_excel)), ancho=11),
        Columna("Estado", lambda r: tipos.get(r.registro.fila_excel) or r.estado, ancho=22),
        *_columnas_comunes(),
        Columna("Fecha y hora BCP", lambda r: r.movimiento.fecha_hora if r.movimiento else None, FECHA_HORA, ancho=21),
        Columna("Dif. seg", lambda r: r.diferencia_seg, "0", ancho=9),
        Columna("Nro Oper BCP", lambda r: r.movimiento.nro_oper if r.movimiento else None, ancho=14),
        Columna("Glosa BCP", lambda r: r.movimiento.glosa.strip() if r.movimiento else None, ancho=24),
        Columna("Cd. Confirmación BCP", lambda r: _cd(r), ancho=18),
        Columna("Motivo", _motivo_revision, ancho=42),
        Columna("Comentario", lambda r: None, ancho=34),
    ]
    _escribir_tabla(ws, columnas, filas, encabezado=NARANJA,
                    relleno=lambda r: COLOR_POR_ESTADO.get(r.estado))


def _hoja_todos(ws, resultados: Sequence[M.Resultado], cfg: M.Config) -> None:
    columnas = [
        Columna("Nro", lambda r: r.registro.crudo.get("Nro"), "0", ancho=7),
        Columna("Estado", lambda r: r.estado, ancho=18),
        *_columnas_comunes(),
        Columna("Nit/C.I.", lambda r: r.registro.crudo.get("Nit/C.I."), ancho=14),
        Columna("Razon Social", lambda r: r.registro.crudo.get("Razon Social"), ancho=22),
        Columna("Tipo Pago", lambda r: r.registro.crudo.get("Tipo Pago"), ancho=12),
        Columna("Canal de Pago", lambda r: r.registro.crudo.get("Canal de Pago"), ancho=15),
        Columna("Estado CBB", lambda r: r.registro.crudo.get("Estado"), ancho=11),
        Columna("Fecha y hora BCP", lambda r: r.movimiento.fecha_hora if r.movimiento else None, FECHA_HORA, ancho=21),
        Columna("Importe BCP", lambda r: M.centavos_a_float(r.movimiento.centavos) if r.movimiento else None,
                MONEDA, ancho=13),
        Columna("Dif. seg", lambda r: r.diferencia_seg, "0", ancho=9),
        Columna("Delta con signo", _delta_con_signo, "+0;-0;0", ancho=15),
        Columna("Nro Oper BCP", lambda r: r.movimiento.nro_oper if r.movimiento else None, ancho=14),
        Columna("Glosa BCP", lambda r: r.movimiento.glosa.strip() if r.movimiento else None, ancho=24),
        Columna("Cd. Confirmación BCP", lambda r: _cd(r), ancho=18),
        Columna("Conflicto ciudad", lambda r: "SI" if M._conflicto_ciudad(r, cfg) else "", ancho=15),
        Columna("Candidatos", lambda r: r.candidatos, "0", ancho=11),
        Columna("Ambiguo", lambda r: "SI" if r.ambiguo else "", ancho=9),
        Columna("Motivo", lambda r: r.motivo, ancho=42),
        Columna("Fila Excel CBB", lambda r: r.registro.fila_excel, "0", ancho=13),
        Columna("Fila Excel BCP", lambda r: r.movimiento.fila_excel if r.movimiento else None, "0", ancho=13),
    ]
    _escribir_tabla(ws, columnas, resultados, encabezado=AZUL_OSCURO,
                    relleno=lambda r: COLOR_POR_ESTADO.get(r.estado))


FORMATOS_RAW = {
    "FechaHora_CBB": FECHA_HORA, "BCP_FechaHora": FECHA_HORA, "BCP_Fecha": "DD/MM/YYYY",
    "Monto": MONEDA, "BCP_Importe": MONEDA,
}


def _hoja_raw(ws, resultados: Sequence[M.Resultado], cfg: M.Config) -> None:
    """Salida tecnica intacta: nombres de campo originales, para trazabilidad."""
    filas = M.a_filas(resultados, cfg)
    columnas = [
        Columna(nombre, lambda fila, clave=nombre: fila[clave], FORMATOS_RAW.get(nombre))
        for nombre in M.COLUMNAS_SALIDA
    ]
    _escribir_tabla(ws, columnas, filas, encabezado=GRIS)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

def _hoja_resumen(ws, datos: dict[str, Any]) -> None:
    ws.sheet_view.showGridLines = False
    for c, ancho in zip("ABCDEFGH", (22, 16, 22, 16, 22, 16, 22, 16)):
        ws.column_dimensions[c].width = ancho

    _titulo(ws, 1, "CRUCE COCHABAMBA vs BCP", 18, AZUL_OSCURO[0], alto=32)
    _titulo(ws, 2, f"Período analizado: {datos['periodo']}", 12, "5B7C99", alto=20)
    _titulo(ws, 3, f"Generado: {dt.datetime.now():%d/%m/%Y %H:%M:%S}", 10, "8095A8", alto=18)

    fila = 5
    _seccion(ws, fila, "UNIVERSO ANALIZADO")
    fila = _tarjetas(ws, fila + 1, [
        ("Registros Cochabamba", datos["total_cbb"], GRIS),
        ("QR Cochabamba", datos["total_qr"], GRIS),
        ("No QR", datos["total_no_qr"], GRIS),
        ("Movimientos BCP", datos["total_bcp"], GRIS),
    ])

    fila += 1
    _seccion(ws, fila, "RESULTADO DEL CRUCE")
    fila = _tarjetas(ws, fila + 1, [
        ("MATCH SEGURO", datos["n_seguro"], VERDE),
        ("MATCH PROBABLE", datos["n_probable"], AZUL),
        ("REVISAR", datos["n_revisar"], NARANJA),
        ("SIN MATCH", datos["n_sin_match"], ROJO),
    ])

    fila += 1
    _tarjetas(ws, fila, [("% ENCONTRADO SOBRE QR COCHABAMBA", datos["pct"], VERDE, "0.00%")], ancho_tarjeta=8)
    fila += 3

    _seccion(ws, fila, "IMPORTES (Bs)")
    fila += 1
    importes = [
        ("Total QR Cochabamba", datos["bs_qr"], None),
        ("MATCH SEGURO", datos["bs_seguro"], VERDE[1]),
        ("MATCH PROBABLE", datos["bs_probable"], AZUL[1]),
        ("REVISAR", datos["bs_revisar"], NARANJA[1]),
        ("SIN MATCH", datos["bs_sin_match"], ROJO[1]),
    ]
    for concepto, valor, color in importes:
        _fila_dato(ws, fila, concepto, valor, MONEDA, color, negrita=color is None)
        fila += 1

    fila += 1
    _seccion(ws, fila, "LEYENDA DE COLORES")
    fila += 1
    for texto, color in (("VERDE — MATCH SEGURO", VERDE[1]), ("AZUL — MATCH PROBABLE", AZUL[1]),
                         ("AMARILLO — REVISAR", NARANJA[1]), ("ROJO — SIN MATCH", ROJO[1]),
                         ("GRIS — NO QR (no entra al cruce)", GRIS[1])):
        celda = ws.cell(row=fila, column=1, value=texto)
        celda.fill = PatternFill("solid", fgColor=color)
        celda.border = BORDE
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=3)
        for c in (2, 3):
            ws.cell(row=fila, column=c).fill = PatternFill("solid", fgColor=color)
            ws.cell(row=fila, column=c).border = BORDE
        fila += 1

    fila += 1
    _seccion(ws, fila, "DISTRIBUCIÓN DE DIFERENCIAS DE TIEMPO")
    fila += 1
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=6)
    ws.merge_cells(start_row=fila, start_column=7, end_row=fila, end_column=8)
    for columna, titulo in ((1, "Diferencia entre la factura y el abono"), (7, "Casos")):
        ws.cell(row=fila, column=columna, value=titulo).font = Font(bold=True, color="FFFFFF")
    for c in range(1, 9):
        ws.cell(row=fila, column=c).fill = PatternFill("solid", fgColor=AZUL_OSCURO[0])
        ws.cell(row=fila, column=c).border = BORDE
    fila += 1
    for rango, casos in datos["distribucion"].items():
        _fila_dato(ws, fila, rango, casos, "0", "FFFFFF")
        fila += 1
    for etiqueta, valor in datos["estadisticas"].items():
        _fila_dato(ws, fila, ETIQUETAS_ESTADISTICA.get(etiqueta, etiqueta), valor, "0.##", GRIS[1])
        fila += 1

    fila += 1
    _seccion(ws, fila, "VALIDACIONES")
    fila += 1
    if datos["alertas"]:
        for nivel, detalle, cantidad in datos["alertas"]:
            color = ROJO[1] if nivel == "CRITICO" else (NARANJA[1] if nivel == "ALERTA" else GRIS[1])
            _fila_dato(ws, fila, f"[{nivel}] {detalle}", cantidad, "0", color)
            fila += 1
    else:
        _fila_dato(ws, fila, "Sin observaciones", 0, "0", VERDE[1])


def _titulo(ws, fila: int, texto: str, tamano: int, color: str, alto: int) -> None:
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=8)
    celda = ws.cell(row=fila, column=1, value=texto)
    celda.font = Font(bold=True, size=tamano, color=color)
    celda.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[fila].height = alto


def _seccion(ws, fila: int, texto: str) -> None:
    celda = ws.cell(row=fila, column=1, value=texto)
    celda.font = Font(bold=True, size=11, color=AZUL_OSCURO[0])
    ws.row_dimensions[fila].height = 20


def _tarjetas(ws, fila: int, tarjetas: Sequence[tuple], ancho_tarjeta: int = 2) -> int:
    """Bloques con color: etiqueta arriba, numero grande abajo."""
    ws.row_dimensions[fila].height = 18
    ws.row_dimensions[fila + 1].height = 30
    for i, tarjeta in enumerate(tarjetas):
        etiqueta, valor, paleta = tarjeta[0], tarjeta[1], tarjeta[2]
        formato = tarjeta[3] if len(tarjeta) > 3 else "#,##0"
        col = 1 + i * ancho_tarjeta
        ws.merge_cells(start_row=fila, start_column=col, end_row=fila, end_column=col + ancho_tarjeta - 1)
        ws.merge_cells(start_row=fila + 1, start_column=col, end_row=fila + 1, end_column=col + ancho_tarjeta - 1)

        celda = ws.cell(row=fila, column=col, value=etiqueta)
        celda.font = Font(bold=True, size=9, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=paleta[0])
        celda.alignment = Alignment(horizontal="center", vertical="center")

        valor_celda = ws.cell(row=fila + 1, column=col, value=valor)
        valor_celda.font = Font(bold=True, size=16, color=paleta[0])
        valor_celda.fill = PatternFill("solid", fgColor=paleta[1])
        valor_celda.alignment = Alignment(horizontal="center", vertical="center")
        valor_celda.number_format = formato

        for f in (fila, fila + 1):
            for c in range(col, col + ancho_tarjeta):
                ws.cell(row=f, column=c).border = BORDE
                if f == fila:
                    ws.cell(row=f, column=c).fill = PatternFill("solid", fgColor=paleta[0])
                else:
                    ws.cell(row=f, column=c).fill = PatternFill("solid", fgColor=paleta[1])
    return fila + 2


def _fila_dato(ws, fila: int, concepto: str, valor: Any, formato: str, color: str | None, negrita: bool = False) -> None:
    """Concepto ancho (A:F) y valor a la derecha (G:H), para que los textos largos quepan."""
    ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=6)
    ws.merge_cells(start_row=fila, start_column=7, end_row=fila, end_column=8)
    celda = ws.cell(row=fila, column=1, value=concepto)
    celda.font = Font(bold=negrita, size=10)
    valor_celda = ws.cell(row=fila, column=7, value=valor)
    valor_celda.number_format = formato
    valor_celda.font = Font(bold=True, size=10)
    valor_celda.alignment = Alignment(horizontal="right")
    for c in range(1, 9):
        ws.cell(row=fila, column=c).border = BORDE
        if color:
            ws.cell(row=fila, column=c).fill = PatternFill("solid", fgColor=color)


# --------------------------------------------------------------------------- #
# Entrada principal
# --------------------------------------------------------------------------- #

def escribir(
    resultados: Sequence[M.Resultado],
    registros: Sequence[M.RegistroCBB],
    movimientos: Sequence[M.MovimientoBCP],
    alertas: Sequence[tuple[str, str, int]],
    cfg: M.Config,
    salida: str,
) -> str:
    por_estado = {e: [r for r in resultados if r.estado == e] for e in
                  (M.ESTADO_SEGURO, M.ESTADO_PROBABLE, M.ESTADO_REVISAR, M.ESTADO_NO_QR)}
    sin_match = [r for r in resultados if r.estado in (M.ESTADO_SIN_MATCH, M.ESTADO_INCOMPLETO)]
    qr = [r for r in resultados if r.estado != M.ESTADO_NO_QR]

    fechas_bcp = [m.fecha_hora for m in movimientos if m.fecha_hora is not None]
    inicio, fin = (min(fechas_bcp), max(fechas_bcp)) if fechas_bcp else (None, None)
    tipos = {r.registro.fila_excel: _tipo_sin_match(r, inicio, fin) for r in sin_match}

    conteo, stats = M.distribucion(resultados)

    def bs(items: Sequence[M.Resultado]) -> float:
        return round(sum(M.centavos_a_float(r.registro.centavos) or 0.0 for r in items), 2)

    fechas_cbb = [r.fecha for r in registros if r.fecha is not None]
    encontrados = sum(len(por_estado[e]) for e in (M.ESTADO_SEGURO, M.ESTADO_PROBABLE, M.ESTADO_REVISAR))

    wb = Workbook()
    wb.remove(wb.active)

    _hoja_resumen(wb.create_sheet("RESUMEN_VISUAL"), {
        "periodo": (f"{min(fechas_cbb):%d/%m/%Y} a {max(fechas_cbb):%d/%m/%Y}" if fechas_cbb else "-"),
        "total_cbb": len(registros),
        "total_qr": len(qr),
        "total_no_qr": len(por_estado[M.ESTADO_NO_QR]),
        "total_bcp": len(movimientos),
        "n_seguro": len(por_estado[M.ESTADO_SEGURO]),
        "n_probable": len(por_estado[M.ESTADO_PROBABLE]),
        "n_revisar": len(por_estado[M.ESTADO_REVISAR]),
        "n_sin_match": len(sin_match),
        "pct": (encontrados / len(qr)) if qr else 0.0,
        "bs_qr": bs(qr),
        "bs_seguro": bs(por_estado[M.ESTADO_SEGURO]),
        "bs_probable": bs(por_estado[M.ESTADO_PROBABLE]),
        "bs_revisar": bs(por_estado[M.ESTADO_REVISAR]),
        "bs_sin_match": bs(sin_match),
        "distribucion": conteo,
        "estadisticas": stats,
        "alertas": alertas,
    })

    _hoja_para_pegar(wb.create_sheet("PARA_PEGAR_CBB"),
                     por_estado[M.ESTADO_SEGURO] + por_estado[M.ESTADO_PROBABLE])
    _hoja_revisar(wb.create_sheet("REVISAR_MANUAL"), por_estado[M.ESTADO_REVISAR])
    _hoja_sin_match(wb.create_sheet("SIN_MATCH"), sin_match, tipos)
    _hoja_no_qr(wb.create_sheet("NO_QR"), por_estado[M.ESTADO_NO_QR])
    _hoja_auditoria(wb.create_sheet("AUDITORIA_EXCEPCIONES"),
                    por_estado[M.ESTADO_PROBABLE] + por_estado[M.ESTADO_REVISAR] + sin_match, tipos)
    _hoja_todos(wb.create_sheet("TODOS"), resultados, cfg)
    _hoja_raw(wb.create_sheet("RAW_MATCH_SEGURO"), por_estado[M.ESTADO_SEGURO], cfg)
    _hoja_raw(wb.create_sheet("RAW_MATCH_PROBABLE"), por_estado[M.ESTADO_PROBABLE], cfg)
    _hoja_raw(wb.create_sheet("RAW_REVISAR"), por_estado[M.ESTADO_REVISAR], cfg)

    wb.save(salida)
    return salida

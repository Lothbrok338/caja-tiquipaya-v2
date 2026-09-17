"""Cierre historico: congela los matches ya aceptados en una corrida anterior.

Subir el QUICKVALLE de un cierre anterior significa que sus matches son
definitivos. Este modulo los saca del universo ANTES de cruzar y reserva sus
Nro Oper, de modo que el motor de matching no vuelve a decidir sobre ellos ni
puede reutilizar su movimiento bancario. El algoritmo de `matcher.emparejar`
no se toca: solo se le entrega menos entrada.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Sequence

import matcher as M

ESTADO_HISTORICO = "MATCH_HISTORICO"
ALERTA_INCONSISTENTE = "ALERTA - CIERRE HISTORICO INCONSISTENTE"

# Encabezados que identifican el PARA_PEGAR_CBB de un QUICKVALLE anterior.
REQUERIDOS_CIERRE = ("Estado", "Origen del match", "Factura", "Nro Oper BCP")

COLUMNAS_CIERRE = {
    "Estado": ("Estado",),
    "Origen": ("Origen del match", "Origen"),
    "Factura": ("Factura", "Numero Factura"),
    "FechaHora CBB": ("Fecha y hora CBB",),
    "Monto": ("Monto Bs", "Monto"),
    "FechaHora BCP": ("Fecha y hora BCP",),
    "Nro Oper": ("Nro Oper BCP", "Nro Oper"),
    "Glosa": ("Glosa BCP", "Glosa"),
    "Cd Confirmacion": ("Cd. Confirmación BCP", "Cd Confirmacion"),
}

OBLIGATORIAS_CIERRE = ("Estado", "Factura", "Nro Oper")


@dataclass(frozen=True)
class RegistroCerrado:
    """Una linea de PARA_PEGAR_CBB de la corrida anterior, ya aceptada."""

    factura: str
    fecha: dt.date | None
    centavos: int | None
    nro_oper: Any
    nro_oper_norm: str
    fecha_hora_bcp: dt.datetime | None
    importe_centavos: int | None
    glosa: str
    cd_confirmacion: Any
    estado_previo: str


def leer_cierre(tabla) -> list[RegistroCerrado]:
    """Lee los matches finales del QUICKVALLE anterior.

    Solo cuentan las filas con Nro Oper: un pendiente o un descartado del cierre
    anterior nunca llega aqui, asi que vuelve a analizarse con normalidad.
    """
    cols = tabla.columnas
    cerrados: list[RegistroCerrado] = []
    for i in range(tabla.fila_encabezado + 1, len(tabla.filas)):
        fila = tabla.filas[i]
        crudo = {c: (fila[idx] if idx < len(fila) else None) for c, idx in cols.items()}
        factura = M.norm_id(crudo.get("Factura"))
        oper = M.norm_id(crudo.get("Nro Oper"))
        if not factura or not oper:
            continue
        fecha_hora = M.redondear_a_segundo(M.a_datetime(crudo.get("FechaHora CBB")))
        cerrados.append(
            RegistroCerrado(
                factura=factura,
                fecha=fecha_hora.date() if fecha_hora else None,
                centavos=M.a_centavos(crudo.get("Monto")),
                nro_oper=crudo.get("Nro Oper"),
                nro_oper_norm=oper,
                fecha_hora_bcp=M.redondear_a_segundo(M.a_datetime(crudo.get("FechaHora BCP"))),
                importe_centavos=M.a_centavos(crudo.get("Monto")),
                glosa="" if crudo.get("Glosa") is None else str(crudo["Glosa"]),
                cd_confirmacion=crudo.get("Cd Confirmacion"),
                estado_previo=str(crudo.get("Estado") or ""),
            )
        )
    return cerrados


@dataclass
class Congelado:
    resultados: list[M.Resultado]
    facturas: set[str]
    opers_reservados: set[str]
    alertas: list[tuple[str, str, int]]


def aplicar(
    registros: Sequence[M.RegistroCBB],
    movimientos: Sequence[M.MovimientoBCP],
    cerrados: Sequence[RegistroCerrado],
) -> Congelado:
    """Convierte el cierre anterior en resultados fijos y reserva sus Nro Oper."""
    por_factura = {M.norm_id(r.crudo.get("Numero Factura")): r for r in registros}
    por_oper: dict[str, M.MovimientoBCP] = {}
    for mov in movimientos:
        por_oper.setdefault(mov.nro_oper_norm, mov)

    resultados: list[M.Resultado] = []
    facturas: set[str] = set()
    opers: set[str] = set()
    problemas: dict[str, int] = {}

    def anotar(detalle: str) -> None:
        problemas[detalle] = problemas.get(detalle, 0) + 1

    for cerrado in cerrados:
        # El Nro Oper queda reservado aunque el pago ya no aparezca: nunca puede
        # volver a usarse para otro match.
        opers.add(cerrado.nro_oper_norm)
        registro = por_factura.get(cerrado.factura)
        if registro is None:
            anotar("el pago cerrado ya no aparece en el reporte de ingresos")
            continue

        facturas.add(cerrado.factura)
        movimiento = por_oper.get(cerrado.nro_oper_norm)
        motivos = []
        if movimiento is None:
            motivos.append("el Nro Oper no existe en el extracto BCP actual")
            movimiento = _movimiento_del_cierre(cerrado)
        elif cerrado.centavos is not None and movimiento.centavos != cerrado.centavos:
            motivos.append("el importe del movimiento BCP cambio")
        if (cerrado.centavos is not None and registro.centavos is not None
                and registro.centavos != cerrado.centavos):
            motivos.append("el monto del pago cambio en el reporte de ingresos")

        motivo = "Congelado del cierre anterior"
        if motivos:
            motivo = f"{ALERTA_INCONSISTENTE}: {'; '.join(motivos)}. Se conserva la asignacion."
            for detalle in motivos:
                anotar(detalle)

        diferencia = None
        if registro.fecha_hora is not None and movimiento.fecha_hora is not None:
            diferencia = round(abs((registro.fecha_hora - movimiento.fecha_hora).total_seconds()), 3)

        resultados.append(
            M.Resultado(registro, movimiento, diferencia, ESTADO_HISTORICO, 0, None, None, False, motivo)
        )

    alertas = [(("CRITICO" if "ya no aparece" in detalle or "no existe" in detalle else "ALERTA"),
                f"Cierre anterior: {detalle}", cantidad)
               for detalle, cantidad in sorted(problemas.items())]
    return Congelado(resultados, facturas, opers, alertas)


def _movimiento_del_cierre(cerrado: RegistroCerrado) -> M.MovimientoBCP:
    """Reconstruye el movimiento aceptado cuando ya no esta en el extracto nuevo.

    No inventa un match: repite el que el usuario ya cerro, para no perderlo.
    """
    return M.MovimientoBCP(
        fila_excel=0,
        crudo={},
        fecha_hora=cerrado.fecha_hora_bcp,
        centavos=cerrado.importe_centavos,
        nro_oper=cerrado.nro_oper,
        nro_oper_norm=cerrado.nro_oper_norm,
        glosa=cerrado.glosa,
        cd_confirmacion=cerrado.cd_confirmacion,
        es_qr=True,
    )

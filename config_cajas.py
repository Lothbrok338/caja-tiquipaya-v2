"""
config_cajas.py — Configuración explícita e inmutable por CAJA.

Única fuente de verdad de lo que distingue una caja de otra: qué hojas SFC
trae su cierre, contra qué cuenta va su HABER normal, con qué nombre se
identifica en SAP, qué valor de la columna CAJA del maestro ATC le
corresponde y si aplica (o no) la regla de RESERVA POSGRADO.

DEFAULT ABSOLUTO: TIQUIPAYA. Toda API histórica que no reciba una caja
explícita se comporta EXACTAMENTE como antes de que este módulo existiera
(mismas hojas, mismas claves de diccionario, mismas cuentas, mismos textos).

Este módulo no lee archivos, no calcula importes y no conoce el motor: solo
describe cajas. La caja NUNCA se infiere por heurística desde el contenido
de un archivo — siempre llega explícita desde el llamador.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CajaConfig:
    """Descripción inmutable de una caja.

    codigo                  identificador estable ("tiquipaya" / "america");
                            es lo que viaja dentro de los dicts del motor y
                            lo que se serializa (nunca el objeto).
    sfcs                    las DOS hojas SFC del cierre, en orden.
    cuenta_haber            cuenta del HABER normal (ambos SFC usan la misma).
    nombre_sap              texto de referencia de cabecera SAP (celda L10).
    atc_caja                valor esperado en la columna CAJA de la hoja
                            "ATC TIQUIPAYA" del maestro (el NOMBRE de esa
                            hoja no cambia para ninguna caja).
    reserva_posgrado        True si la caja aplica la regla POSGRADO RESERVA.
    cuenta_reserva_posgrado cuenta CxP del HABER adicional de la reserva;
                            None si la caja no aplica la regla.
    """

    codigo: str
    sfcs: tuple
    cuenta_haber: str
    nombre_sap: str
    atc_caja: str
    reserva_posgrado: bool = False
    cuenta_reserva_posgrado: str = None

    def clave_sfc(self, sfc):
        """Clave del diccionario `cierre` para una hoja SFC: 'SFC101' ->
        'sfc101'. Para TIQUIPAYA devuelve exactamente las claves históricas
        ('sfc101'/'sfc102'), por eso leer_cierre() no rompe a ningún
        consumidor previo."""
        return sfc.lower()

    @property
    def claves_sfc(self):
        return tuple(self.clave_sfc(sfc) for sfc in self.sfcs)

    def texto_haber(self, sfc):
        """Texto de posición (SGTXT) del HABER normal. Para TIQUIPAYA
        reproduce LITERALMENTE los textos históricos
        ('RECAUDACION CAJA SFC101' / 'RECAUDACION CAJA SFC102')."""
        return f"RECAUDACION CAJA {sfc}"

    def origen_universo(self, sfc):
        """Origen de la partida HABER normal: 'UNIVERSO_SFC101' para
        TIQUIPAYA (idéntico al histórico)."""
        return f"UNIVERSO_{sfc}"

    @property
    def origenes_universo(self):
        return tuple(self.origen_universo(sfc) for sfc in self.sfcs)


TIQUIPAYA = CajaConfig(
    codigo="tiquipaya",
    sfcs=("SFC101", "SFC102"),
    cuenta_haber="110101001",
    nombre_sap="CAJA TIQUIPAYA",
    atc_caja="TIQUIPAYA",
    reserva_posgrado=False,
    cuenta_reserva_posgrado=None,
)

AMERICA = CajaConfig(
    codigo="america",
    sfcs=("SFC107", "SFC108"),
    cuenta_haber="110101003",
    nombre_sap="CAJA AMERICA",
    atc_caja="AMERICA",
    reserva_posgrado=True,
    cuenta_reserva_posgrado="210103003",
)

CAJA_POR_DEFECTO = TIQUIPAYA

CAJAS = {
    TIQUIPAYA.codigo: TIQUIPAYA,
    AMERICA.codigo: AMERICA,
}


def resolver_caja(valor=None):
    """Normaliza a CajaConfig. Acepta None (-> TIQUIPAYA, el default
    absoluto), un CajaConfig ya resuelto, o el `codigo` de una caja
    conocida. Un código desconocido FALLA CERRADO: nunca se adivina una
    caja ni se cae silenciosamente al default."""
    if valor is None:
        return CAJA_POR_DEFECTO
    if isinstance(valor, CajaConfig):
        return valor
    if isinstance(valor, str):
        caja = CAJAS.get(valor.strip().lower())
        if caja is not None:
            return caja
    raise ValueError(
        f"CAJA_DESCONOCIDA: {valor!r}. Cajas válidas: {sorted(CAJAS)}."
    )


# Abreviaturas de mes para la ASIGNACION de la partida RESERVA POSGRADO
# (POSTG-<MES>). Deliberadamente SEPARADAS de las abreviaturas del resto
# del motor: septiembre es "SEPT" aquí y "SEP" en el resto (regla del
# usuario, no un descuido).
_MESES_POSTG = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SEPT", 10: "OCT", 11: "NOV", 12: "DIC",
}

TEXTO_RESERVA_POSGRADO = "RESERVA POSGRADO"
ORIGEN_RESERVA_POSGRADO = "RESERVA_POSGRADO"


def asignacion_reserva_posgrado(fecha_iso):
    """'POSTG-<MES>' a partir de la fecha del cierre (YYYY-MM-DD).
    None si no hay fecha (nunca se inventa una)."""
    if not fecha_iso:
        return None
    _, mes, _ = fecha_iso.split("-")
    return f"POSTG-{_MESES_POSTG[int(mes)]}"

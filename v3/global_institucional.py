"""v3/global_institucional.py — Fusionador GLOBAL INSTITUCIONAL.

Toma los DOS SAP GLOBAL mensuales YA GENERADOS por `consolidador_mensual.py`
(uno de CAJA TIQUIPAYA, uno de CAJA AMÉRICA) y produce un TERCER archivo,
puramente derivado y de solo lectura sobre sus dos entradas: el SAP GLOBAL
INSTITUCIONAL del periodo, con las partidas de TIQUIPAYA primero y las de
AMÉRICA después, en el mismo orden en que aparecen en cada GLOBAL de origen.

Reutiliza SIN reimplementar el parser ni la escritura SAP de
`consolidador_mensual.py`:

  - `leer_y_validar_sap_diario()` para leer y validar CADA GLOBAL de entrada
    (misma hoja "1", misma cabecera fija fila 10, mismas partidas desde fila
    16 — el layout de un SAP GLOBAL es idéntico al de un SAP diario, así que
    la misma función de V2 sirve tal cual, pasándole la `CajaConfig` real de
    cada origen para que valide la cabecera L10 esperada);
  - `construir_metadata_cabecera_global()` / `escribir_sap_global()` para la
    cabecera y la escritura de las partidas fusionadas;
  - `validar_guardarrieles_salida()` para los guardarraíles de --salida
    (nunca la plantilla, nunca un GLOBAL de origen, exige --force para
    reemplazar);
  - `periodo_sap_global()` / `nombre_sap_global()` para el nombre canónico.

Este módulo agrega ÚNICAMENTE lo que le es propio:

  1. una pseudo `CajaConfig` INSTITUCIONAL, LOCAL a este módulo (nunca se
     agrega a `config_cajas.CAJAS`: INSTITUCIONAL no es una caja pública del
     flujo diario, solo una identidad de cabecera/nombre para el archivo
     fusionado);
  2. la concatenación determinística TIQ+AME con trazabilidad por fila
     (CAJA / ARCHIVO_ORIGEN / FILA_ORIGEN) en columnas nuevas AL FINAL de la
     fila (AA/AB/AC — deliberadamente lejos de B..W, que ya usa
     `escribir_sap_global()`, y de columnas como "X" que otras pruebas del
     proyecto usan como sentinela de "no tocar" en la plantilla SAP), sin
     tocar ninguna posición que ya consumen CONTROL 1
     (`control_asignaciones.py`, columnas hasta R) ni CONTROL 3
     (`v3/control3_modos.py`);
  3. el sidecar `MAPA_ORIGEN_INSTITUCIONAL_<MES>_<AÑO>.json`;
  4. la normalización determinística del .xlsx de salida: `openpyxl` fecha
     cada entrada del zip y `docProps/core.xml:dcterms:modified` con la hora
     real de ejecución, lo que hace NO determinista el SHA-256 del archivo
     entre corridas idénticas (verificado empíricamente). Este módulo
     reescribe el zip después de `escribir_sap_global()` con fechas fijas y
     sin ningún timestamp de "ahora", así la misma pareja GLOBAL TIQ+AME
     produce siempre el mismo SHA-256.

MUY IMPORTANTE — solo lectura sobre las dos entradas: los dos GLOBAL de
origen se abren EXCLUSIVAMENTE vía `leer_y_validar_sap_diario()` (que ya usa
`read_only=True`); nunca se llama `.save()` sobre ellos.

Validaciones fail-closed (nunca se adivina ni se sigue con datos parciales):
  - falta el GLOBAL TIQ o el GLOBAL AME -> error;
  - el nombre de alguno de los dos no sigue la convención canónica del
    periodo/caja pedido (`SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx` /
    `SAP_GLOBAL_AME_<MES>_<AÑO>.xlsx`) -> error;
  - `--salida` no sigue la convención canónica institucional
    (`SAP_GLOBAL_INSTITUCIONAL_<MES>_<AÑO>.xlsx`) -> error;
  - TIQ y AME apuntan al mismo archivo (origen ambiguo: no hay forma segura
    de distinguir qué partida es de qué caja) -> error;
  - cualquiera de los dos GLOBAL está corrupto (cabecera inesperada,
    partidas inconsistentes, no cuadra Cargo/Haber) -> error, nunca se
    fusiona parcialmente.
"""

import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_cajas as cfg  # noqa: E402  (misma fuente de verdad de caja que consolidador_mensual.py)
import consolidador_mensual as cm  # noqa: E402  (reutilizado tal cual — parser y escritura SAP, sin cambios)


# ---------------------------------------------------------------------------
# Pseudo CajaConfig INSTITUCIONAL — LOCAL a este módulo. Deliberadamente NO
# se agrega a `config_cajas.CAJAS`: `cfg.resolver_caja("institucional")`
# (por código, como llegaría de cualquier flujo diario) sigue fallando con
# CAJA_DESCONOCIDA, exactamente igual que antes de este módulo. Solo se usa
# pasando el objeto YA RESUELTO (`CAJA_INSTITUCIONAL`) directamente a las
# funciones de `consolidador_mensual.py`/`control_asignaciones.py` que
# aceptan una `CajaConfig` ya resuelta (ambas usan `cfg.resolver_caja(caja)`,
# que no exige que la instancia esté registrada).
# ---------------------------------------------------------------------------

CAJA_INSTITUCIONAL = cfg.CajaConfig(
    codigo="institucional",
    sfcs=(),
    cuenta_haber="",
    nombre_sap="INSTITUCIONAL",
    atc_caja="INSTITUCIONAL",
    prefijo_archivo="INSTITUCIONAL",
    reserva_posgrado=False,
    cuenta_reserva_posgrado=None,
)


# ---------------------------------------------------------------------------
# Columnas de trazabilidad — a la derecha de todo lo que ya escribe
# `escribir_sap_global()` (usa hasta la columna W); CONTROL 1 solo lee hasta
# R, CONTROL 3 reutiliza esas mismas funciones de V2 tal cual, así que X/Y/Z
# quedan fuera de cualquier posición que ambos consumen.
# ---------------------------------------------------------------------------

_COL_CAJA = "AA"
_COL_ARCHIVO_ORIGEN = "AB"
_COL_FILA_ORIGEN = "AC"
_FILA_ENCABEZADO_TECNICO = 14
_FILA_ENCABEZADO_DESCRIPCION = 15


def nombre_mapa_origen(anio, mes):
    return f"MAPA_ORIGEN_INSTITUCIONAL_{cm.periodo_sap_global(anio, mes)}.json"


# ---------------------------------------------------------------------------
# Validaciones fail-closed sobre las dos entradas y la salida
# ---------------------------------------------------------------------------

def _validar_nombre_canonico(ruta, anio, mes, caja, etiqueta):
    esperado = cm.nombre_sap_global(anio, mes, caja)
    obtenido = os.path.basename(ruta)
    if obtenido != esperado:
        raise RuntimeError(
            f"NOMBRE_{etiqueta}_NO_CANONICO: se esperaba '{esperado}', se "
            f"recibió '{obtenido}' (ruta: {ruta})."
        )


def _validar_entradas(ruta_tiq, ruta_ame, anio, mes):
    if not ruta_tiq or not os.path.isfile(ruta_tiq):
        raise RuntimeError(f"GLOBAL_TIQ_NO_ENCONTRADO: {ruta_tiq}")
    if not ruta_ame or not os.path.isfile(ruta_ame):
        raise RuntimeError(f"GLOBAL_AME_NO_ENCONTRADO: {ruta_ame}")

    if os.path.abspath(ruta_tiq) == os.path.abspath(ruta_ame):
        raise RuntimeError(
            f"ORIGEN_AMBIGUO: GLOBAL TIQ y GLOBAL AME apuntan al mismo "
            f"archivo ({os.path.abspath(ruta_tiq)}); no hay forma segura de "
            f"distinguir qué partida pertenece a qué caja."
        )

    if mes not in cm._MES_NOMBRE:
        raise RuntimeError(f"MES_INVALIDO: {mes!r} (debe ser 1-12)")

    _validar_nombre_canonico(ruta_tiq, anio, mes, cfg.TIQUIPAYA, "GLOBAL_TIQ")
    _validar_nombre_canonico(ruta_ame, anio, mes, cfg.AMERICA, "GLOBAL_AME")


def _leer_global_o_error(ruta, caja, etiqueta):
    resultado = cm.leer_y_validar_sap_diario(ruta, caja)
    if resultado["problemas"]:
        raise RuntimeError(
            f"GLOBAL_{etiqueta}_CORRUPTO: {os.path.basename(ruta)}: "
            + "; ".join(resultado["problemas"])
        )
    return resultado["partidas"]


# ---------------------------------------------------------------------------
# Determinismo — openpyxl fecha cada entrada del zip y
# docProps/core.xml:dcterms:modified con la hora real de ejecución; eso hace
# NO determinista el SHA-256 del .xlsx entre corridas idénticas. Se reescribe
# el zip con fechas fijas y sin ningún timestamp de "ahora".
# ---------------------------------------------------------------------------

_FECHA_ZIP_FIJA = (1980, 1, 1, 0, 0, 0)
_MODIFICADO_FIJO = b"2000-01-01T00:00:00Z"
_RE_DCTERMS_MODIFIED = re.compile(
    rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)"
)


def _normalizar_determinismo_xlsx(ruta):
    """Reescribe `ruta` (un .xlsx ya guardado) con fechas de zip fijas, sin
    `dcterms:modified` dinámico y con las entradas en orden estable, para
    que el mismo contenido produzca siempre el mismo SHA-256."""
    with zipfile.ZipFile(ruta, "r") as zin:
        entradas = []
        for info in zin.infolist():
            datos = zin.read(info.filename)
            if info.filename == "docProps/core.xml":
                datos = _RE_DCTERMS_MODIFIED.sub(
                    rb"\g<1>" + _MODIFICADO_FIJO + rb"\g<2>", datos
                )
            entradas.append((info.filename, info.external_attr, datos))

    entradas.sort(key=lambda item: item[0])

    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as zout:
        for nombre, external_attr, datos in entradas:
            info_nuevo = zipfile.ZipInfo(nombre, date_time=_FECHA_ZIP_FIJA)
            info_nuevo.compress_type = zipfile.ZIP_DEFLATED
            info_nuevo.external_attr = external_attr
            zout.writestr(info_nuevo, datos)


# ---------------------------------------------------------------------------
# Trazabilidad — columnas X/Y/Z + sidecar
# ---------------------------------------------------------------------------

def _escribir_columnas_trazabilidad(ruta_salida, origenes):
    """Abre la copia ya escrita por `escribir_sap_global()` (nunca la
    plantilla ni los GLOBAL de origen) y agrega, a la derecha de todas las
    columnas existentes, CAJA/ARCHIVO_ORIGEN/FILA_ORIGEN por fila."""
    wb = cm._abrir_libro(ruta_salida)
    try:
        ws = wb[cm._HOJA_SAP]

        ws[f"{_COL_CAJA}{_FILA_ENCABEZADO_TECNICO}"] = "CAJA"
        ws[f"{_COL_ARCHIVO_ORIGEN}{_FILA_ENCABEZADO_TECNICO}"] = "ARCHIVO_ORIGEN"
        ws[f"{_COL_FILA_ORIGEN}{_FILA_ENCABEZADO_TECNICO}"] = "FILA_ORIGEN"

        ws[f"{_COL_CAJA}{_FILA_ENCABEZADO_DESCRIPCION}"] = (
            "Caja de origen (trazabilidad GLOBAL INSTITUCIONAL)"
        )
        ws[f"{_COL_ARCHIVO_ORIGEN}{_FILA_ENCABEZADO_DESCRIPCION}"] = (
            "Nombre del SAP GLOBAL mensual de origen"
        )
        ws[f"{_COL_FILA_ORIGEN}{_FILA_ENCABEZADO_DESCRIPCION}"] = (
            "Fila (hoja \"1\") en el SAP GLOBAL de origen"
        )

        for offset, origen in enumerate(origenes):
            fila = cm._FILA_PRIMERA_PARTIDA + offset
            ws[f"{_COL_CAJA}{fila}"] = origen["caja"]
            ws[f"{_COL_ARCHIVO_ORIGEN}{fila}"] = origen["archivo_origen"]
            ws[f"{_COL_FILA_ORIGEN}{fila}"] = origen["fila_origen"]

        wb.save(ruta_salida)
    finally:
        wb.close()


def _construir_mapa_origen(origenes):
    return {
        str(cm._FILA_PRIMERA_PARTIDA + offset): dict(origen)
        for offset, origen in enumerate(origenes)
    }


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def fusionar_global_institucional(
    ruta_global_tiq, ruta_global_ame, anio, mes, ruta_plantilla, ruta_salida,
    ruta_mapa_origen=None, force=False,
):
    """Fusiona GLOBAL TIQ + GLOBAL AME (TIQ primero) en un único
    SAP_GLOBAL_INSTITUCIONAL_<MES>_<AÑO>.xlsx, con trazabilidad por fila
    (CAJA/ARCHIVO_ORIGEN/FILA_ORIGEN) y un sidecar
    MAPA_ORIGEN_INSTITUCIONAL_<MES>_<AÑO>.json.

    Determinístico: la misma pareja exacta de GLOBAL TIQ+AME produce siempre
    el mismo contenido y el mismo SHA-256 del .xlsx institucional.

    Falla cerrado (RuntimeError) ante: GLOBAL TIQ/AME faltante, nombre no
    canónico (de cualquiera de las tres rutas: TIQ/AME/salida), origen
    ambiguo (TIQ y AME son el mismo archivo), o cualquiera de los dos GLOBAL
    de entrada corrupto. Nunca escribe nada — ni el .xlsx ni el sidecar — si
    alguna validación falla.
    """
    if not os.path.isfile(ruta_plantilla):
        raise RuntimeError(f"PLANTILLA_NO_ENCONTRADA: {ruta_plantilla}")

    _validar_entradas(ruta_global_tiq, ruta_global_ame, anio, mes)
    _validar_nombre_canonico(ruta_salida, anio, mes, CAJA_INSTITUCIONAL, "SALIDA_INSTITUCIONAL")

    cm.validar_guardarrieles_salida(
        ruta_salida, ruta_plantilla, [ruta_global_tiq, ruta_global_ame], force,
        CAJA_INSTITUCIONAL,
    )

    partidas_tiq = _leer_global_o_error(ruta_global_tiq, cfg.TIQUIPAYA, "TIQ")
    partidas_ame = _leer_global_o_error(ruta_global_ame, cfg.AMERICA, "AME")

    nombre_tiq = os.path.basename(ruta_global_tiq)
    nombre_ame = os.path.basename(ruta_global_ame)

    origenes = [
        {"caja": cfg.TIQUIPAYA.codigo, "archivo_origen": nombre_tiq,
         "fila_origen": cm._FILA_PRIMERA_PARTIDA + i}
        for i in range(len(partidas_tiq))
    ] + [
        {"caja": cfg.AMERICA.codigo, "archivo_origen": nombre_ame,
         "fila_origen": cm._FILA_PRIMERA_PARTIDA + i}
        for i in range(len(partidas_ame))
    ]

    todas_partidas = list(partidas_tiq) + list(partidas_ame)

    metadata = cm.construir_metadata_cabecera_global(anio, mes, CAJA_INSTITUCIONAL)
    cm.escribir_sap_global(todas_partidas, ruta_plantilla, ruta_salida, metadata)
    _escribir_columnas_trazabilidad(ruta_salida, origenes)
    _normalizar_determinismo_xlsx(ruta_salida)

    ruta_mapa_origen = ruta_mapa_origen or os.path.join(
        os.path.dirname(os.path.abspath(ruta_salida)) or ".",
        nombre_mapa_origen(anio, mes),
    )
    mapa_origen = _construir_mapa_origen(origenes)
    with open(ruta_mapa_origen, "w", encoding="utf-8") as f:
        json.dump(mapa_origen, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    return {
        "anio": anio,
        "mes": mes,
        "periodo": cm.periodo_sap_global(anio, mes),
        "ruta_global_tiq": os.path.abspath(ruta_global_tiq),
        "ruta_global_ame": os.path.abspath(ruta_global_ame),
        "ruta_global_institucional": os.path.abspath(ruta_salida),
        "ruta_mapa_origen": os.path.abspath(ruta_mapa_origen),
        "cantidad_partidas_tiq": len(partidas_tiq),
        "cantidad_partidas_ame": len(partidas_ame),
        "cantidad_partidas_total": len(todas_partidas),
        "sha256_global_institucional": cm._sha256_archivo(ruta_salida),
    }


def construir_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fusionador GLOBAL INSTITUCIONAL — concatena el SAP "
                     "GLOBAL mensual de CAJA TIQUIPAYA y el de CAJA AMÉRICA "
                     "(TIQ primero) en SAP_GLOBAL_INSTITUCIONAL_<MES>_<AÑO>.xlsx, "
                     "con trazabilidad CAJA/ARCHIVO_ORIGEN/FILA_ORIGEN."
    )
    parser.add_argument("--anio", required=True, type=int)
    parser.add_argument("--mes", required=True, type=int, choices=range(1, 13), metavar="1-12")
    parser.add_argument("--global-tiq", required=True, dest="global_tiq")
    parser.add_argument("--global-ame", required=True, dest="global_ame")
    parser.add_argument("--plantilla", required=True)
    parser.add_argument("--salida", required=True)
    parser.add_argument("--mapa-origen", default=None, dest="mapa_origen")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)

    try:
        resultado = fusionar_global_institucional(
            args.global_tiq, args.global_ame, args.anio, args.mes,
            args.plantilla, args.salida, args.mapa_origen, args.force,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"GLOBAL INSTITUCIONAL {args.mes:02d}/{args.anio}: "
        f"{resultado['cantidad_partidas_total']} partidas "
        f"(TIQ={resultado['cantidad_partidas_tiq']}, "
        f"AME={resultado['cantidad_partidas_ame']})"
    )
    print(f"SAP GLOBAL institucional: {resultado['ruta_global_institucional']}")
    print(f"Mapa de origen: {resultado['ruta_mapa_origen']}")
    print(f"SHA-256: {resultado['sha256_global_institucional']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

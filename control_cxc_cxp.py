"""
control_cxc_cxp.py — CONTROL 3: seguimiento acumulado de Cuentas por Cobrar
(CxC) y Cuentas por Pagar (CxP) transitorias del SAP GLOBAL mensual de Caja
Tiquipaya.

Módulo NUEVO y AISLADO. CONTROL 3 es exclusivamente de seguimiento/
auditoría: LEE el GLOBAL, CALCULA saldos, ACUMULA entre meses, CLASIFICA
(ABIERTO/CERRADO/REVISAR), GENERA un reporte Excel para el auditor y
MANTIENE un histórico técnico. Nunca modifica el SAP GLOBAL, el motor
diario, la consolidación mensual, CONTROL 1 (asignaciones), cuentas,
asignaciones ni importes. El GLOBAL se abre SIEMPRE con
`read_only=True, data_only=True` y nunca recibe `.save()`.

UNIVERSO (primera versión — exactamente estas 6 cuentas, ninguna otra):

    CxC UNIDADES      110201002
    CxP UNIDADES      210103002
    CxC EMPRESAS      110201003
    CxP EMPRESAS      210103003
    CxC PARTICULARES  110201004
    CxP PARTICULARES  210103004

LLAVE (permanente, entre meses): CUENTA_MAYOR + ASIGNACION. La misma
ASIGNACION bajo dos cuentas distintas son dos entidades lógicas distintas.
Una partida de una de las 6 cuentas SIN Asignacion nunca se acumula ni se
agrupa de forma silenciosa: se reporta como `ASIGNACION_FALTANTE_CXC_CXP`
en el JSON (fila GLOBAL, cuenta, glosa, debe, haber) y queda fuera de toda
llave — nunca crea ni actualiza una fila del histórico. Además aparece en
el Excel humano como fila EXCEPCIONAL (una por cada ocurrencia, nunca
agrupadas): ESTADO=REVISAR, ASIGNACION="ASIGNACION FALTANTE",
DEBE_MES/HABER_MES de esa partida puntual, y OBSERVACION_SISTEMA
identificando la fila GLOBAL de origen — ordenadas junto a REVISAR, antes
de cualquier otra fila (ver `_filas_excel_asignacion_faltante`).

Layout del GLOBAL (idéntico a sap_writer.py/consolidador_mensual.py/
control_asignaciones.py, nunca reinterpretado aquí — hoja EXACTA "1",
partidas desde la fila 16):

    C = CuentaMayor   D = TextoPosicion (glosa)   E = Cargo/Debe
    F = Haber         O = FechaValor              R = Asignacion (ZUONR)

La hoja "1" es OBLIGATORIA (ERROR_TECNICO si no existe, sin fallback a
otra hoja) y el nombre del GLOBAL debe seguir la convención canónica
SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx (ERROR_TECNICO si no, sin inferir el
periodo de otra forma).

FÓRMULA DE SALDO (acumulado, nunca solo del mes):

    CxC (110201002/110201003/110201004): SALDO = DEBE_ACUMULADO - HABER_ACUMULADO
    CxP (210103002/210103003/210103004): SALDO = HABER_ACUMULADO - DEBE_ACUMULADO

    SALDO > 0  -> ABIERTO
    SALDO == 0 -> CERRADO
    SALDO < 0  -> REVISAR (sobrecompensación; el saldo se muestra tal cual,
                  NUNCA en valor absoluto)

OBSERVACION_SISTEMA: texto determinístico (sin IA), reconstruido en cada
corrida a partir de un pequeño historial de eventos por llave
(`historial_estados`, campo técnico adicional — ver HISTORICO más abajo)
que registra APERTURA/CIERRE/REAPERTURA/SOBRECOMPENSACION. Permite narrar
correctamente reaperturas sucesivas sin necesitar una tabla de movimientos
mensuales separada.

OBSERVACION_AUDITOR: texto libre, memoria del auditor. Python NUNCA la
sobrescribe automáticamente; solo se actualiza vía el puente JSON
(`--observaciones-json`), y solo esa columna — nunca saldo/estado/
importes/asignación/cuenta.

CIERRE MANUAL POR AUDITOR (misma interfaz: OBSERVACION_AUDITOR): si el
texto EMPIEZA con "CERRADO MANUALMENTE" (case-insensitive, sin espacios
extremos, tolerante a tildes SOLO para comparar — ver _es_cierre_manual;
una mención aislada de "cerrado" en cualquier otro lugar del texto NUNCA
activa nada), CONTROL 3 lo interpreta de forma determinística (sin IA)
como el cierre declarado por el auditor porque otra área ya lo resolvió
fuera del GLOBAL. NUNCA modifica el saldo calculado, NUNCA crea un
movimiento artificial, NUNCA toca el GLOBAL: el histórico conserva el
saldo contable real. Campos técnicos: `cierre_manual` ("SI" mientras esté
VIGENTE) y `periodo_cierre_manual` (periodo de la declaración más
reciente — NUNCA se borra, ni siquiera si se invalida). Mientras vigente,
ESTADO=CERRADO MANUALMENTE en el Excel y, sin movimiento nuevo en meses
posteriores, la llave se OCULTA del Excel mensual (sigue en
HISTORICO_CXC_CXP.csv). Un movimiento DEBE/HABER posterior invalida el
cierre (cierre_manual -> "", periodo_cierre_manual se conserva) y hace
reaparecer la llave automáticamente con ESTADO=REVISAR forzado
(independiente del signo real del saldo). Una nueva declaración
"CERRADO MANUALMENTE..." posterior vuelve a cerrarla.

HISTORICO TÉCNICO (`HISTORICO_CXC_CXP.csv`): UNA fila permanente por
CUENTA+ASIGNACION (nunca una fila nueva por mes). Columnas:

    cuenta, tipo, asignacion, debe_acumulado, haber_acumulado, saldo,
    estado, periodo_primera_aparicion, periodo_ultimo_movimiento,
    periodo_ultimo_cierre, observacion_sistema, observacion_auditor,
    sha256_global_ultimo, fecha_actualizacion, historial_estados,
    cierre_manual, periodo_cierre_manual

`historial_estados` es el único campo técnico adicional agregado sobre el
mínimo pedido: una lista JSON compacta de eventos [tipo, periodo] (ver
`_nuevos_eventos`/`construir_observacion_sistema`) estrictamente necesaria
para reconstruir observaciones correctas ante reaperturas múltiples, sin
crear una tabla de movimientos mensuales separada.

IDEMPOTENCIA: no se vuelve a acumular el mismo periodo+SHA del GLOBAL. Se
verifica EXCLUSIVAMENTE contra un LIBRO DE PERIODOS (sidecar
`05_CONTROLES/HISTORICO_CXC_CXP_PERIODOS.json`, junto al CSV histórico
`05_CONTROLES/HISTORICO_CXC_CXP.csv`), que es la fuente AUTORITATIVA E
INMUTABLE de qué periodo+SHA ya fue aplicado — nunca un histórico de
movimientos, solo una entrada `{sha256_global, estado, ...}` por periodo.
Es necesario porque una fila del histórico (acumulador por CUENTA+
ASIGNACION) se sigue reescribiendo en periodos posteriores: su propio
`sha256_global_ultimo`/`periodo_ultimo_movimiento` es MUTABLE y por sí
solo NUNCA es fuente confiable para decidir sobre un periodo antiguo ya
aplicado — un movimiento posterior de la MISMA llave en otro periodo
sobrescribe esos campos, y usarlos para invalidar el periodo antiguo
causaría una reacumulación indebida (bug real, corregido; ver
`tests/test_control_cxc_cxp.py::TestConsistenciaHistoricoPeriodos.
test_periodo_antiguo_no_se_reacumula_tras_movimiento_posterior_de_la_misma_llave`).

Mecanismo de escritura — transacción de dos fases con recuperación
determinística (el libro de periodos y el CSV histórico son archivos
separados, cada `guardar_*` atómico por separado vía `.tmp`+`os.replace`,
pero sin una transacción única entre ambos):

    PENDIENTE  ->  escritura atómica del histórico  ->  APLICADO

`libro_periodos[periodo]` se escribe con `estado="PENDIENTE"` ANTES de
tocar el histórico, y se sobrescribe a `estado="APLICADO"` DESPUÉS de que
`guardar_historico` ya completó. `_estado_idempotencia` decide, en este
orden:

- Sin registro para el periodo -> procesar normalmente.
- Registro con SHA distinto al actual -> SIEMPRE
  `GLOBAL_MODIFICADO_REQUIERE_REVISION`, sin importar su estado
  (PENDIENTE o APLICADO) ni el histórico.
- Registro con el MISMO SHA y `estado="APLICADO"` -> SIEMPRE
  `YA_PROCESADO_SIN_CAMBIOS`, sin reevaluar nada más — un periodo
  APLICADO nunca vuelve a acumularse, sin importar qué le haya pasado
  después a esa fila del histórico en periodos posteriores.
- Registro con el MISMO SHA y `estado="PENDIENTE"` -> corte a mitad de
  camino de la corrida que dejó esa marca; SOLO aquí es seguro contrastar
  contra el histórico (`_historico_ya_refleja_periodo`, porque esa misma
  corrida interrumpida es la ÚLTIMA que pudo haber tocado esas filas): si
  el histórico ya lo refleja -> se sella `APLICADO` sin reacumular; si no
  -> se reprocesa de cero (el histórico todavía no tiene esos importes,
  así que acumular ahora es la primera vez real, nunca una duplicación).

PUENTE JSON DE OBSERVACIONES (`--observaciones-json`): igual que
`--revision-json` en CONTROL 1, resuelve el mismo problema técnico (no
transportar/reconstruir XLSX vía Base64). Cowork lee
CONTROL_CXC_CXP_<MES>_<AÑO>.xlsx desde Drive y genera un JSON pequeño:

    {
      "periodo": "AGOSTO_2026",
      "sha256_global": "...",
      "observaciones": [
        {"cuenta": "110201003", "asignacion": "FORTALEZA",
         "observacion_auditor": "Esperando transferencia de Clínica."}
      ]
    }

El auditor nunca edita este JSON. Se valida contra el estado ACTUAL del
histórico (periodo y sha256_global deben coincidir; cada CUENTA+ASIGNACION
debe existir ya en el histórico) y se aplica todo-o-nada: si CUALQUIER
entrada falla, no se aplica NINGUNA. Solo puede escribir
`observacion_auditor` — nunca crea llaves, nunca toca saldo/estado/
importes/asignación/cuenta.

TRANSPORTE: solo rutas de archivo locales ya materializadas. Nunca Base64,
nunca Google Drive, nunca clientes de LLM.

Uso:
    python control_cxc_cxp.py \
        --global /ruta/SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx \
        --historico /ruta/HISTORICO_CXC_CXP.csv \
        --salida-xlsx /ruta/CONTROL_CXC_CXP_AGOSTO_2026.xlsx \
        --salida-json /ruta/CONTROL_CXC_CXP_AGOSTO_2026.json

    Modo seguro (no escribe absolutamente nada):
    python control_cxc_cxp.py --global ... --historico ... \
        --salida-xlsx ... --salida-json ... --dry-run

    Aplicar únicamente observaciones del auditor (vía puente JSON):
    python control_cxc_cxp.py --global ... --historico ... \
        --salida-xlsx ... --salida-json ... \
        --observaciones-json /ruta/CONTROL_CXC_CXP_AGOSTO_2026_OBSERVACIONES.json
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Universo de cuentas controladas (ÚNICAS 6 de esta primera versión).
# ---------------------------------------------------------------------------

_TIPO_CXC = "CXC"
_TIPO_CXP = "CXP"

# cuenta_mayor -> (tipo_cuenta interno, etiqueta visible en el Excel)
_CUENTAS_CONTROL = {
    "110201002": (_TIPO_CXC, "CxC UNIDADES"),
    "210103002": (_TIPO_CXP, "CxP UNIDADES"),
    "110201003": (_TIPO_CXC, "CxC EMPRESAS"),
    "210103003": (_TIPO_CXP, "CxP EMPRESAS"),
    "110201004": (_TIPO_CXC, "CxC PARTICULARES"),
    "210103004": (_TIPO_CXP, "CxP PARTICULARES"),
}

# ---------------------------------------------------------------------------
# Layout del GLOBAL (idéntico a sap_writer.py/consolidador_mensual.py/
# control_asignaciones.py — nunca reinterpretado aquí).
# ---------------------------------------------------------------------------

_HOJA_SAP = "1"
_FILA_PRIMERA_PARTIDA = 16

_COL_CUENTA = "C"
_COL_GLOSA = "D"
_COL_CARGO = "E"
_COL_HABER = "F"
_COL_FECHA_VALOR = "O"
_COL_ASIGNACION = "R"

# Convención canónica OBLIGATORIA del nombre del GLOBAL mensual.
_RE_NOMBRE_GLOBAL = re.compile(r"^SAP_GLOBAL_TIQ_([A-Za-z]+)_(\d{4})\.xlsx$", re.IGNORECASE)

_ESTADO_ABIERTO = "ABIERTO"
_ESTADO_CERRADO = "CERRADO"
_ESTADO_REVISAR = "REVISAR"

# Estado EFECTIVO (solo para el Excel humano; nunca se usa en la lógica
# contable ni en `estado`) cuando la llave está bajo cierre manual del
# auditor vigente (ver CIERRE MANUAL más abajo).
_ESTADO_CERRADO_MANUALMENTE = "CERRADO MANUALMENTE"

# Marcador de ASIGNACION para la fila EXCEPCIONAL de una partida sin
# Asignacion (ver _filas_excel_asignacion_faltante). Nunca es una llave
# real del histórico: no se guarda en HISTORICO_CXC_CXP.csv.
_ASIGNACION_FALTANTE_MARCADOR = "ASIGNACION FALTANTE"

_TIPO_EVENTO_APERTURA = "APERTURA"
_TIPO_EVENTO_CIERRE = "CIERRE"
_TIPO_EVENTO_REAPERTURA = "REAPERTURA"
_TIPO_EVENTO_SOBRECOMPENSACION = "SOBRECOMPENSACION"
_TIPO_EVENTO_REVISAR_SIN_APERTURA = "REVISAR_SIN_APERTURA"

# CIERRE MANUAL POR AUDITOR: activado únicamente por el texto de
# OBSERVACION_AUDITOR (nunca un botón/flag/columna nueva que llenar). No
# se integra al historial_estados contable (APERTURA/CIERRE/...): es un
# overlay independiente que NUNCA toca saldo/estado/importes/asignación/
# cuenta — ver _es_cierre_manual/_actualizar_fila/aplicar_observaciones.
_PREFIJO_CIERRE_MANUAL = "CERRADO MANUALMENTE"
_CIERRE_MANUAL_SI = "SI"

_COLUMNAS_HISTORICO = [
    "cuenta", "tipo", "asignacion", "debe_acumulado", "haber_acumulado", "saldo",
    "estado", "periodo_primera_aparicion", "periodo_ultimo_movimiento",
    "periodo_ultimo_cierre", "observacion_sistema", "observacion_auditor",
    "sha256_global_ultimo", "fecha_actualizacion",
    # Campo técnico adicional (ver docstring): historial de eventos para
    # reconstruir OBSERVACION_SISTEMA ante reaperturas múltiples.
    "historial_estados",
    # Cierre manual del auditor (ver docstring, sección CIERRE MANUAL):
    # cierre_manual="SI" mientras el cierre manual esté VIGENTE (sin
    # movimiento posterior que lo invalide); periodo_cierre_manual
    # conserva PARA SIEMPRE el periodo de la declaración más reciente,
    # incluso después de invalidarse (nunca se borra el antecedente).
    "cierre_manual", "periodo_cierre_manual",
]

_HOJA_CONTROL = "CONTROL"
_COLUMNAS_CONTROL_XLSX = [
    "PERIODO_CONTROL", "CUENTA", "TIPO", "ASIGNACION", "DEBE_MES", "HABER_MES",
    "DEBE_ACUMULADO", "HABER_ACUMULADO", "SALDO", "ESTADO",
    "OBSERVACION_SISTEMA", "OBSERVACION_AUDITOR",
]
_COLUMNAS_IMPORTE_XLSX = {"DEBE_MES", "HABER_MES", "DEBE_ACUMULADO", "HABER_ACUMULADO", "SALDO"}
_ANCHOS_CONTROL_XLSX = {
    "PERIODO_CONTROL": 16, "CUENTA": 14, "TIPO": 18, "ASIGNACION": 18,
    "DEBE_MES": 14, "HABER_MES": 14, "DEBE_ACUMULADO": 16, "HABER_ACUMULADO": 16,
    "SALDO": 14, "ESTADO": 12, "OBSERVACION_SISTEMA": 55, "OBSERVACION_AUDITOR": 45,
}

_RELLENO_ABIERTO = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
_FUENTE_ABIERTO = Font(color="9C6500")
_RELLENO_CERRADO = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
_FUENTE_CERRADO = Font(color="006100")
_RELLENO_REVISAR = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_FUENTE_REVISAR = Font(color="9C0006", bold=True)
_RELLENO_CERRADO_MANUALMENTE = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
_FUENTE_CERRADO_MANUALMENTE = Font(color="404040")

_ORDEN_ESTADO_XLSX = {
    _ESTADO_REVISAR: 0, _ESTADO_ABIERTO: 1, _ESTADO_CERRADO: 2,
    _ESTADO_CERRADO_MANUALMENTE: 3,
}


class HojaNoEncontradaError(RuntimeError):
    """La hoja EXACTA "1" no existe en el GLOBAL. Nunca se hace fallback a
    otra hoja (ver leer_partidas_global)."""


# ---------------------------------------------------------------------------
# Utilidades básicas (Excel / hashing / Decimal) — sin reinterpretar
# contabilidad, solo normalización segura de celdas.
# ---------------------------------------------------------------------------

def _hash_archivo(ruta):
    hasher = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            hasher.update(bloque)
    return hasher.hexdigest()


def _abrir_libro(ruta, **kwargs):
    return openpyxl.load_workbook(ruta, **kwargs)


def _decimal_celda(valor):
    """Convierte el valor de una celda de importe a Decimal con 2
    decimales, o None si la celda está vacía/no numérica. Nunca usa float
    como lógica de saldo (ver regla Decimal del proyecto)."""
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        dec = valor
    elif isinstance(valor, bool):
        return None
    elif isinstance(valor, int):
        dec = Decimal(valor)
    elif isinstance(valor, float):
        dec = Decimal(str(valor))
    else:
        texto = str(valor).strip()
        if not texto:
            return None
        try:
            dec = Decimal(texto)
        except InvalidOperation:
            return None
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _decimal_o_cero(texto):
    """Como _decimal_celda, pero para valores ya guardados como texto en
    el histórico CSV: vacío/ilegible -> Decimal("0.00") (nunca None, para
    poder sumar directamente sobre el acumulado)."""
    if texto in (None, ""):
        return Decimal("0.00")
    try:
        return Decimal(str(texto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0.00")


def _texto_celda(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto if texto else None


def _fecha_celda(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime.datetime):
        return valor.date().isoformat()
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    return str(valor).strip()


def _normalizar_cuenta(valor):
    """Normaliza CuentaMayor a texto comparable de forma segura, sin
    asumir un tipo de origen fijo (Excel puede entregarla como str, int o
    float — p. ej. 110201002.0)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return texto


def _formato_bs(valor):
    """Formato boliviano Bs 1.234,56 (miles con punto, decimales con
    coma). El signo se conserva tal cual — NUNCA valor absoluto."""
    negativo = valor < 0
    texto = f"{abs(valor):.2f}"
    entero, _, decimales = texto.partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    entero_fmt = ".".join(grupos)
    resultado = f"{entero_fmt},{decimales}"
    return f"-{resultado}" if negativo else resultado


def cargar_json(ruta):
    """Nunca lanza: devuelve None si el archivo no existe o no es JSON
    válido — el llamador lo trata como "sin datos"."""
    if not ruta or not os.path.isfile(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Periodo (a partir del nombre canónico del GLOBAL). OBLIGATORIO, sin
# fallback: un nombre no canónico detiene el control.
# ---------------------------------------------------------------------------

def _derivar_periodo(nombre_archivo_global):
    if not nombre_archivo_global:
        return None
    m = _RE_NOMBRE_GLOBAL.match(nombre_archivo_global)
    if not m:
        return None
    mes, anio = m.groups()
    return f"{mes.upper()}_{anio}"


def _periodo_legible(periodo):
    """"AGOSTO_2026" -> "AGOSTO 2026" (para OBSERVACION_SISTEMA)."""
    return periodo.replace("_", " ")


# ---------------------------------------------------------------------------
# Lectura del GLOBAL (SOLO LECTURA — nunca se guarda nada sobre él aquí).
# ---------------------------------------------------------------------------

def leer_partidas_global(ruta_global):
    """Lee TODAS las partidas de la hoja EXACTA "1" (fila 16+) y devuelve
    únicamente las que pertenecen a una de las 6 cuentas controladas
    (_CUENTAS_CONTROL) — cualquier otra cuenta se ignora por completo, sin
    leerla ni reportarla. Nunca hace fallback a otra hoja: si "1" no
    existe, lanza HojaNoEncontradaError. Se detiene en la primera fila
    donde CuentaMayor y Asignacion están ambas vacías."""
    wb = _abrir_libro(ruta_global, data_only=True, read_only=True)
    try:
        if _HOJA_SAP not in wb.sheetnames:
            raise HojaNoEncontradaError(_HOJA_SAP)
        ws = wb[_HOJA_SAP]

        partidas = []
        fila = _FILA_PRIMERA_PARTIDA
        while True:
            cuenta_raw = ws[f"{_COL_CUENTA}{fila}"].value
            asignacion_raw = ws[f"{_COL_ASIGNACION}{fila}"].value
            if (cuenta_raw in (None, "")) and (asignacion_raw in (None, "")):
                break

            cuenta = _normalizar_cuenta(cuenta_raw)
            if cuenta not in _CUENTAS_CONTROL:
                fila += 1
                continue

            debe = _decimal_celda(ws[f"{_COL_CARGO}{fila}"].value) or Decimal("0.00")
            haber = _decimal_celda(ws[f"{_COL_HABER}{fila}"].value) or Decimal("0.00")
            partidas.append({
                "fila_sap": fila,
                "cuenta_mayor": cuenta,
                "asignacion": _texto_celda(asignacion_raw),
                "glosa": _texto_celda(ws[f"{_COL_GLOSA}{fila}"].value),
                "fecha_valor": _fecha_celda(ws[f"{_COL_FECHA_VALOR}{fila}"].value),
                "debe": debe,
                "haber": haber,
            })
            fila += 1
        return partidas
    finally:
        wb.close()


def clasificar_partidas(partidas):
    """Separa las partidas del universo controlado en:
    - candidatas: tienen Asignacion -> se pueden agrupar por llave.
    - faltantes: Asignacion vacía -> NUNCA se acumulan ni se agrupan de
      forma silenciosa; se reportan (ASIGNACION_FALTANTE_CXC_CXP)."""
    candidatas = []
    faltantes = []
    for p in partidas:
        if not p["asignacion"]:
            faltantes.append({
                "tipo": "ASIGNACION_FALTANTE_CXC_CXP",
                "fila_global": p["fila_sap"],
                "cuenta": p["cuenta_mayor"],
                "glosa": p["glosa"],
                "debe": str(p["debe"]),
                "haber": str(p["haber"]),
            })
        else:
            candidatas.append(p)
    return candidatas, faltantes


def agrupar_movimientos_mes(candidatas):
    """Agrupa por llave CUENTA+ASIGNACION y suma DEBE/HABER del mes
    (Decimal). Nunca mezcla llaves de cuentas distintas: (cuenta, "X") y
    (otra_cuenta, "X") son entradas independientes del dict."""
    grupos = {}
    for p in candidatas:
        clave = (p["cuenta_mayor"], p["asignacion"])
        acumulado = grupos.setdefault(clave, {"debe": Decimal("0.00"), "haber": Decimal("0.00")})
        acumulado["debe"] += p["debe"]
        acumulado["haber"] += p["haber"]
    return grupos


# ---------------------------------------------------------------------------
# Cálculo de saldo / estado
# ---------------------------------------------------------------------------

def calcular_saldo(tipo_cuenta, debe_acumulado, haber_acumulado):
    if tipo_cuenta == _TIPO_CXC:
        return debe_acumulado - haber_acumulado
    return haber_acumulado - debe_acumulado  # _TIPO_CXP


def determinar_estado(saldo):
    if saldo > 0:
        return _ESTADO_ABIERTO
    if saldo == 0:
        return _ESTADO_CERRADO
    return _ESTADO_REVISAR


# ---------------------------------------------------------------------------
# Histórico (HISTORICO_CXC_CXP.csv) — una fila permanente por CUENTA+ASIGNACION.
# ---------------------------------------------------------------------------

def cargar_historico(ruta_historico):
    """Devuelve {(cuenta, asignacion): fila_dict}. Si el archivo no
    existe, devuelve {} — el primer GLOBAL procesado actúa como punto
    inicial del seguimiento."""
    if not ruta_historico or not os.path.isfile(ruta_historico):
        return {}
    with open(ruta_historico, "r", encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    return {(fila.get("cuenta"), fila.get("asignacion")): fila for fila in filas}


def guardar_historico(ruta_historico, historico_dict):
    """Reescritura atómica del CSV completo (una fila por llave, orden
    determinístico por cuenta+asignacion)."""
    directorio = os.path.dirname(os.path.abspath(ruta_historico))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    ruta_tmp = f"{ruta_historico}.tmp"
    filas_ordenadas = sorted(historico_dict.values(), key=lambda f: (f["cuenta"], f["asignacion"]))
    with open(ruta_tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNAS_HISTORICO)
        writer.writeheader()
        for fila in filas_ordenadas:
            writer.writerow({col: fila.get(col, "") for col in _COLUMNAS_HISTORICO})
    os.replace(ruta_tmp, ruta_historico)


def _ruta_libro_periodos(ruta_historico):
    """Sidecar de idempotencia: <HISTORICO>_PERIODOS.json, junto al CSV
    histórico. NUNCA es un histórico de movimientos — solo {periodo:
    {sha256_global, fecha_ejecucion}}, una entrada por periodo ya
    aplicado, necesaria porque las filas del histórico (acumulador) se
    siguen reescribiendo en periodos posteriores."""
    base, _ext = os.path.splitext(ruta_historico)
    return f"{base}_PERIODOS.json"


def _cargar_libro_periodos(ruta_historico):
    datos = cargar_json(_ruta_libro_periodos(ruta_historico))
    return datos if isinstance(datos, dict) else {}


def _guardar_libro_periodos(ruta_historico, libro_periodos):
    ruta = _ruta_libro_periodos(ruta_historico)
    directorio = os.path.dirname(os.path.abspath(ruta))
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    ruta_tmp = f"{ruta}.tmp"
    with open(ruta_tmp, "w", encoding="utf-8") as f:
        json.dump(libro_periodos, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(ruta_tmp, ruta)


_PERIODO_PENDIENTE = "PENDIENTE"
_PERIODO_APLICADO = "APLICADO"


def _historico_ya_refleja_periodo(historico_dict, periodo, sha_actual):
    """True si YA existe al menos una fila del histórico cuyo
    periodo_ultimo_movimiento/sha256_global_ultimo coincide con
    (periodo, sha_actual). ÚNICO uso legítimo: resolver un registro
    PENDIENTE del libro de periodos (ver _estado_idempotencia) — en ese
    momento es seguro, porque esa misma corrida interrumpida es la ÚLTIMA
    que pudo haber tocado estas filas (nada corrió después de la marca
    PENDIENTE y antes de ahora). NUNCA se usa para decidir sobre un
    periodo ya APLICADO: ese campo es mutable (una fila se reescribe en
    periodos posteriores) y por sí solo NO es una fuente confiable para
    invalidar un periodo antiguo — el libro de periodos es la única
    fuente autoritativa e inmutable para eso."""
    return any(
        fila.get("periodo_ultimo_movimiento") == periodo and fila.get("sha256_global_ultimo") == sha_actual
        for fila in historico_dict.values()
    )


def _estado_idempotencia(historico_dict, libro_periodos, periodo, sha_actual):
    """El libro de periodos (HISTORICO_CXC_CXP_PERIODOS.json) es la
    fuente AUTORITATIVA E INMUTABLE de qué periodo+SHA ya fue aplicado —
    nunca se invalida un registro `APLICADO` a partir de campos mutables
    del histórico (`periodo_ultimo_movimiento`/`sha256_global_ultimo`),
    que se siguen reescribiendo en periodos posteriores para la MISMA
    llave. Reglas, en este orden:

    - Sin registro para este periodo -> None (nunca procesado, seguir
      normalmente).
    - Registro con SHA distinto al actual -> SIEMPRE
      GLOBAL_MODIFICADO_REQUIERE_REVISION, sin importar su estado
      (PENDIENTE o APLICADO) ni el histórico.
    - Registro con el MISMO SHA y estado APLICADO -> SIEMPRE
      YA_PROCESADO_SIN_CAMBIOS (autoritativo; nunca se reevalúa contra el
      histórico — esto es lo que corrige el caso reportado: un
      movimiento posterior de la MISMA llave en otro periodo ya no puede
      hacer que este periodo antiguo vuelva a acumularse).
    - Registro con el MISMO SHA y estado PENDIENTE -> corte a mitad de
      camino de la corrida que dejó esa marca (mecanismo PENDIENTE ->
      escritura atómica del histórico -> APLICADO, ver ejecutar_control).
      Solo AQUÍ es seguro usar _historico_ya_refleja_periodo para decidir
      si el histórico llegó a escribirse: si sí ->
      "RECUPERAR_APLICADO" (el llamador sella APLICADO sin reacumular);
      si no -> "RECUPERAR_PENDIENTE" (el llamador reprocesa de cero; el
      histórico todavía no tiene esos importes, así que acumular ahora es
      la primera vez real, nunca una duplicación)."""
    registro = libro_periodos.get(periodo)
    if registro is None:
        return None

    if registro.get("sha256_global") != sha_actual:
        return "GLOBAL_MODIFICADO_REQUIERE_REVISION"

    if registro.get("estado") == _PERIODO_APLICADO:
        return "YA_PROCESADO_SIN_CAMBIOS"

    # estado == PENDIENTE con el mismo SHA.
    if _historico_ya_refleja_periodo(historico_dict, periodo, sha_actual):
        return "RECUPERAR_APLICADO"
    return "RECUPERAR_PENDIENTE"


# ---------------------------------------------------------------------------
# OBSERVACION_SISTEMA — determinístico, reconstruido a partir del
# historial de eventos de cada llave (APERTURA/CIERRE/REAPERTURA/
# SOBRECOMPENSACION/REVISAR_SIN_APERTURA).
# ---------------------------------------------------------------------------

def _cargar_historial(fila_hist):
    texto = fila_hist.get("historial_estados") if fila_hist else None
    if not texto:
        return []
    try:
        datos = json.loads(texto)
    except (TypeError, ValueError):
        return []
    return [{"tipo": tipo, "periodo": periodo} for tipo, periodo in datos]


def _serializar_historial(historial):
    compacto = [[e["tipo"], e["periodo"]] for e in historial]
    return json.dumps(compacto, ensure_ascii=False, separators=(",", ":"))


def _nuevos_eventos(historial, prev_estado, nuevo_estado, periodo_actual):
    """Devuelve los eventos NUEVOS a anexar a `historial` (no lo
    modifica). `prev_estado` es None si la llave es nueva este periodo."""
    tuvo_apertura_antes = any(e["tipo"] == _TIPO_EVENTO_APERTURA for e in historial)

    if prev_estado is None:
        if nuevo_estado == _ESTADO_ABIERTO:
            return [{"tipo": _TIPO_EVENTO_APERTURA, "periodo": periodo_actual}]
        if nuevo_estado == _ESTADO_CERRADO:
            # Abre y cierra en el mismo mes: ambos eventos con el mismo periodo.
            return [
                {"tipo": _TIPO_EVENTO_APERTURA, "periodo": periodo_actual},
                {"tipo": _TIPO_EVENTO_CIERRE, "periodo": periodo_actual},
            ]
        return [{"tipo": _TIPO_EVENTO_REVISAR_SIN_APERTURA, "periodo": periodo_actual}]

    if prev_estado == nuevo_estado:
        return []

    if nuevo_estado == _ESTADO_ABIERTO:
        tipo = _TIPO_EVENTO_REAPERTURA if tuvo_apertura_antes else _TIPO_EVENTO_APERTURA
        return [{"tipo": tipo, "periodo": periodo_actual}]
    if nuevo_estado == _ESTADO_CERRADO:
        return [{"tipo": _TIPO_EVENTO_CIERRE, "periodo": periodo_actual}]
    # nuevo_estado == REVISAR
    tipo = _TIPO_EVENTO_SOBRECOMPENSACION if tuvo_apertura_antes else _TIPO_EVENTO_REVISAR_SIN_APERTURA
    return [{"tipo": tipo, "periodo": periodo_actual}]


def _frase_evento(evento):
    periodo_legible = _periodo_legible(evento["periodo"])
    tipo = evento["tipo"]
    if tipo == _TIPO_EVENTO_APERTURA:
        return f"Cuenta abierta {periodo_legible}."
    if tipo == _TIPO_EVENTO_CIERRE:
        return f"Cerrada {periodo_legible}."
    if tipo == _TIPO_EVENTO_REAPERTURA:
        return f"Reabierta {periodo_legible}."
    if tipo == _TIPO_EVENTO_SOBRECOMPENSACION:
        return f"Sobrecompensación detectada {periodo_legible}."
    if tipo == _TIPO_EVENTO_REVISAR_SIN_APERTURA:
        return f"Saldo negativo detectado {periodo_legible} sin apertura previa registrada."
    return ""


def _ultimo_cierre(historial):
    for evento in reversed(historial):
        if evento["tipo"] == _TIPO_EVENTO_CIERRE:
            return evento["periodo"]
    return ""


def construir_observacion_sistema(historial, estado_actual, saldo_actual, periodo_actual):
    """Reconstruye el texto completo a partir de TODO el historial de
    eventos + una cláusula final según el estado ACTUAL. Determinístico:
    misma entrada -> mismo texto, siempre."""
    frases = [_frase_evento(e) for e in historial]
    ultimo_evento = historial[-1] if historial else None
    continuando = not (ultimo_evento and ultimo_evento["periodo"] == periodo_actual)
    periodo_legible_actual = _periodo_legible(periodo_actual)
    saldo_fmt = _formato_bs(saldo_actual)

    if estado_actual == _ESTADO_ABIERTO:
        if continuando:
            frases.append(f"Continúa abierta a {periodo_legible_actual}.")
        frases.append(f"Saldo pendiente Bs {saldo_fmt}.")
    elif estado_actual == _ESTADO_CERRADO:
        if continuando:
            frases.append(f"Continúa cerrada a {periodo_legible_actual}.")
    else:  # REVISAR
        if continuando:
            frases.append(f"Continúa en REVISAR a {periodo_legible_actual}.")
        frases.append(f"Saldo Bs {saldo_fmt}. REVISAR.")

    return " ".join(f for f in frases if f)


# ---------------------------------------------------------------------------
# Cierre manual del auditor: activado ÚNICAMENTE por el texto de
# OBSERVACION_AUDITOR (nunca un botón/flag/columna nueva). Comparación
# case-insensitive, sin espacios extremos, tolerante a tildes.
# ---------------------------------------------------------------------------

def _normalizar_para_comparar(texto):
    """Solo para COMPARAR contra el prefijo CERRADO MANUALMENTE — nunca
    se usa para modificar el texto real de observacion_auditor, que se
    guarda siempre tal cual lo escribió el auditor."""
    texto = (texto or "").strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def _es_cierre_manual(observacion_auditor):
    """True si observacion_auditor EMPIEZA con "CERRADO MANUALMENTE"
    (una mención aislada de "cerrado" en cualquier otro lugar del texto
    NUNCA activa el cierre manual — p. ej. "Todavía no está cerrado")."""
    return _normalizar_para_comparar(observacion_auditor).startswith(_PREFIJO_CIERRE_MANUAL)


# ---------------------------------------------------------------------------
# Actualización de una fila del histórico (una llave CUENTA+ASIGNACION).
# ---------------------------------------------------------------------------

def _actualizar_fila(clave, tipo_cuenta, tipo_label, prev_row, debe_mes, haber_mes,
                      periodo_actual, sha_actual, ahora):
    tocado_este_mes = debe_mes != Decimal("0.00") or haber_mes != Decimal("0.00")
    cierre_manual_vigente = bool(prev_row) and prev_row.get("cierre_manual") == _CIERRE_MANUAL_SI

    # Llave bajo cierre manual VIGENTE y sin movimiento nuevo: se
    # CONGELA tal cual (nunca se re-renderiza ni se re-evalúa mientras no
    # haya un movimiento real que la invalide). El ocultamiento del Excel
    # en meses posteriores se decide en _construir_filas_excel.
    if cierre_manual_vigente and not tocado_este_mes:
        return dict(prev_row)

    cuenta, asignacion = clave
    prev_debe = _decimal_o_cero(prev_row.get("debe_acumulado")) if prev_row else Decimal("0.00")
    prev_haber = _decimal_o_cero(prev_row.get("haber_acumulado")) if prev_row else Decimal("0.00")
    debe_acumulado = prev_debe + debe_mes
    haber_acumulado = prev_haber + haber_mes
    saldo = calcular_saldo(tipo_cuenta, debe_acumulado, haber_acumulado)
    estado = determinar_estado(saldo)
    prev_estado = prev_row.get("estado") if prev_row else None

    historial = _cargar_historial(prev_row)
    historial_actualizado = historial + _nuevos_eventos(historial, prev_estado, estado, periodo_actual)

    periodo_primera_aparicion = (
        prev_row.get("periodo_primera_aparicion") if prev_row and prev_row.get("periodo_primera_aparicion")
        else periodo_actual
    )
    periodo_ultimo_movimiento = (
        periodo_actual if tocado_este_mes
        else (prev_row.get("periodo_ultimo_movimiento", "") if prev_row else "")
    )
    sha256_global_ultimo = (
        sha_actual if tocado_este_mes
        else (prev_row.get("sha256_global_ultimo", "") if prev_row else "")
    )

    observacion_sistema = construir_observacion_sistema(historial_actualizado, estado, saldo, periodo_actual)

    # GUARDRAIL: movimiento DEBE/HABER posterior a un cierre manual
    # VIGENTE invalida ese cierre (nunca se borra periodo_cierre_manual,
    # que conserva el antecedente para siempre) y fuerza REVISAR — sin
    # importar el signo real del saldo recalculado — para que la llave
    # vuelva a aparecer automáticamente en el Excel. El marcador
    # transitorio `_revisar_forzado` (no es columna del histórico) le
    # indica a _construir_filas_excel el ESTADO a mostrar este run.
    revisar_forzado = False
    periodo_cierre_manual = prev_row.get("periodo_cierre_manual", "") if prev_row else ""
    if cierre_manual_vigente and tocado_este_mes:
        revisar_forzado = True
        observacion_sistema = (
            f"Movimiento posterior a cierre manual detectado {_periodo_legible(periodo_actual)}. REVISAR."
        )

    fila = {
        "cuenta": cuenta,
        "tipo": tipo_label,
        "asignacion": asignacion,
        "debe_acumulado": str(debe_acumulado),
        "haber_acumulado": str(haber_acumulado),
        "saldo": str(saldo),
        "estado": estado,
        "periodo_primera_aparicion": periodo_primera_aparicion,
        "periodo_ultimo_movimiento": periodo_ultimo_movimiento,
        "periodo_ultimo_cierre": _ultimo_cierre(historial_actualizado),
        "observacion_sistema": observacion_sistema,
        "observacion_auditor": prev_row.get("observacion_auditor", "") if prev_row else "",
        "sha256_global_ultimo": sha256_global_ultimo,
        "fecha_actualizacion": ahora,
        "historial_estados": _serializar_historial(historial_actualizado),
        "cierre_manual": "",  # un movimiento nuevo siempre desactiva el cierre manual vigente
        "periodo_cierre_manual": periodo_cierre_manual,
    }
    if revisar_forzado:
        fila["_revisar_forzado"] = True
    return fila


# ---------------------------------------------------------------------------
# Puente JSON de observaciones del auditor (--observaciones-json).
# ---------------------------------------------------------------------------

def aplicar_observaciones(datos, periodo, sha_actual, historico_dict, ahora):
    """Valida el JSON puente contra el estado ACTUAL del histórico (nunca
    confianza ciega) y, si TODO es válido, aplica los cambios EN
    `historico_dict` (mutación in-place) — SOLO el campo
    observacion_auditor de llaves YA existentes. Todo o nada: si cualquier
    entrada falla, no se aplica ninguna. Devuelve (ok, problemas,
    cantidad_aplicadas)."""
    problemas = []
    if not isinstance(datos, dict):
        return False, ["OBSERVACIONES_JSON_MAL_FORMADO"], 0

    if datos.get("periodo") != periodo:
        problemas.append(f"PERIODO_NO_COINCIDE:esperado={periodo!r}:recibido={datos.get('periodo')!r}")
    if datos.get("sha256_global") != sha_actual:
        problemas.append("SHA256_GLOBAL_NO_COINCIDE")
    if problemas:
        return False, problemas, 0

    observaciones = datos.get("observaciones")
    if not isinstance(observaciones, list):
        return False, ["OBSERVACIONES_LISTA_MAL_FORMADA"], 0

    vistas = set()
    validas = []
    for entrada in observaciones:
        if not isinstance(entrada, dict):
            problemas.append("OBSERVACION_MAL_FORMADA")
            continue

        cuenta = _normalizar_cuenta(entrada.get("cuenta"))
        asignacion = _texto_celda(entrada.get("asignacion"))
        if not cuenta or not asignacion:
            problemas.append(f"CUENTA_O_ASIGNACION_INVALIDA:{entrada!r}")
            continue

        clave = (cuenta, asignacion)
        if clave in vistas:
            problemas.append(f"OBSERVACION_DUPLICADA:cuenta={cuenta}:asignacion={asignacion}")
            continue
        vistas.add(clave)

        if clave not in historico_dict:
            problemas.append(f"LLAVE_INEXISTENTE:cuenta={cuenta}:asignacion={asignacion}")
            continue

        texto = entrada.get("observacion_auditor")
        if not isinstance(texto, str):
            problemas.append(f"OBSERVACION_AUDITOR_INVALIDA:cuenta={cuenta}:asignacion={asignacion}")
            continue

        validas.append((clave, texto))

    if problemas:
        return False, problemas, 0

    for clave, texto in validas:
        fila = historico_dict[clave]
        fila["observacion_auditor"] = texto
        fila["fecha_actualizacion"] = ahora

        # Interpretación determinística (nunca IA) de CERRADO MANUALMENTE:
        # ocurre SIEMPRE dentro de CONTROL 3, nunca en el puente en sí.
        # NUNCA toca saldo/estado/importes/asignación/cuenta — solo estos
        # dos campos técnicos + el texto mostrado en OBSERVACION_SISTEMA.
        if _es_cierre_manual(texto):
            fila["cierre_manual"] = _CIERRE_MANUAL_SI
            fila["periodo_cierre_manual"] = periodo
            fila["observacion_sistema"] = (
                f"Cierre manual registrado {_periodo_legible(periodo)}. "
                f"Saldo contable al cierre Bs {_formato_bs(Decimal(fila['saldo']))}."
            )
            fila.pop("_revisar_forzado", None)  # un nuevo cierre manual reemplaza cualquier marca previa

    return True, [], len(validas)


# ---------------------------------------------------------------------------
# Excel humano (CONTROL_CXC_CXP_<MES>_<AÑO>.xlsx) — hoja única "CONTROL".
# ---------------------------------------------------------------------------

def _filas_excel_asignacion_faltante(faltantes, periodo_actual):
    """Una fila EXCEPCIONAL por cada partida sin Asignacion de las 6
    cuentas (nunca agrupadas, nunca acumuladas, nunca una llave del
    histórico): ESTADO=REVISAR, ASIGNACION=_ASIGNACION_FALTANTE_MARCADOR,
    DEBE_MES/HABER_MES de esa partida puntual, DEBE_ACUMULADO/
    HABER_ACUMULADO/SALDO vacíos (no hay acumulación real que mostrar) y
    OBSERVACION_SISTEMA identificando la fila GLOBAL de origen."""
    filas = []
    for f in faltantes:
        tipo_label = _CUENTAS_CONTROL.get(f["cuenta"], (None, f["cuenta"]))[1]
        filas.append({
            "PERIODO_CONTROL": periodo_actual,
            "CUENTA": f["cuenta"],
            "TIPO": tipo_label,
            "ASIGNACION": _ASIGNACION_FALTANTE_MARCADOR,
            "DEBE_MES": Decimal(f["debe"]),
            "HABER_MES": Decimal(f["haber"]),
            "DEBE_ACUMULADO": "",
            "HABER_ACUMULADO": "",
            "SALDO": "",
            "ESTADO": _ESTADO_REVISAR,
            "OBSERVACION_SISTEMA": (
                f"Asignación faltante en fila GLOBAL {f['fila_global']}. No incorporada al histórico."
            ),
            "OBSERVACION_AUDITOR": "",
            "_fila_global": f["fila_global"],
        })
    return filas


def _oculta_del_excel_por_cierre_manual(fila, periodo_actual):
    """CERRADO MANUALMENTE + sin movimiento nuevo = oculto del Excel
    mensual (permanece únicamente en HISTORICO_CXC_CXP.csv). Solo se
    muestra en el periodo exacto de la declaración (o redeclaración)."""
    return fila.get("cierre_manual") == _CIERRE_MANUAL_SI and fila.get("periodo_cierre_manual") != periodo_actual


def _estado_mostrado_excel(fila):
    """Estado EFECTIVO para el Excel (nunca se guarda en `estado`, que
    sigue siendo el estado contable puro): REVISAR forzado si un
    movimiento acaba de invalidar un cierre manual vigente;
    CERRADO MANUALMENTE si sigue vigente; si no, el estado contable tal
    cual."""
    if fila.get("_revisar_forzado"):
        return _ESTADO_REVISAR
    if fila.get("cierre_manual") == _CIERRE_MANUAL_SI:
        return _ESTADO_CERRADO_MANUALMENTE
    return fila["estado"]


def _construir_filas_excel(historico_dict, grupos_mes, periodo_actual, faltantes=None):
    filas = list(_filas_excel_asignacion_faltante(faltantes or [], periodo_actual))
    for clave, fila in historico_dict.items():
        if _oculta_del_excel_por_cierre_manual(fila, periodo_actual):
            continue
        mov = grupos_mes.get(clave)
        debe_mes = mov["debe"] if mov else Decimal("0.00")
        haber_mes = mov["haber"] if mov else Decimal("0.00")
        filas.append({
            "PERIODO_CONTROL": periodo_actual,
            "CUENTA": fila["cuenta"],
            "TIPO": fila["tipo"],
            "ASIGNACION": fila["asignacion"],
            "DEBE_MES": debe_mes,
            "HABER_MES": haber_mes,
            "DEBE_ACUMULADO": Decimal(fila["debe_acumulado"]),
            "HABER_ACUMULADO": Decimal(fila["haber_acumulado"]),
            "SALDO": Decimal(fila["saldo"]),
            "ESTADO": _estado_mostrado_excel(fila),
            "OBSERVACION_SISTEMA": fila["observacion_sistema"],
            "OBSERVACION_AUDITOR": fila["observacion_auditor"],
        })

    def _clave_orden(f):
        # Las filas de asignación faltante van arriba, junto a REVISAR
        # (grupo -1, antes que el propio grupo REVISAR real).
        if f["ASIGNACION"] == _ASIGNACION_FALTANTE_MARCADOR:
            return (-1, f["CUENTA"], f.get("_fila_global", 0))
        return (_ORDEN_ESTADO_XLSX.get(f["ESTADO"], 9), f["CUENTA"], f["ASIGNACION"])

    filas.sort(key=_clave_orden)
    return filas


def guardar_control_xlsx(ruta, filas):
    """Escribe CONTROL_CXC_CXP_<MES>_<AÑO>.xlsx: hoja única "CONTROL",
    encabezados en negrita, autofiltro, fila superior congelada, texto
    ajustado en OBSERVACION_SISTEMA/OBSERVACION_AUDITOR, formato numérico
    legible en importes y relleno visual por ESTADO (sin alterar datos).
    Nunca protege la hoja: el auditor debe poder escribir su observación."""
    directorio = os.path.dirname(os.path.abspath(ruta))
    if directorio:
        os.makedirs(directorio, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = _HOJA_CONTROL

    ws.append(_COLUMNAS_CONTROL_XLSX)
    for celda in ws[1]:
        celda.font = Font(bold=True)

    for fila in filas:
        ws.append([fila.get(col, "") for col in _COLUMNAS_CONTROL_XLSX])

    ultima_fila = ws.max_row
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(_COLUMNAS_CONTROL_XLSX))}{ultima_fila}"

    for idx, col in enumerate(_COLUMNAS_CONTROL_XLSX, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = _ANCHOS_CONTROL_XLSX.get(col, 16)

    if ultima_fila > 1:
        idx_estado = _COLUMNAS_CONTROL_XLSX.index("ESTADO") + 1
        idx_obs_sistema = _COLUMNAS_CONTROL_XLSX.index("OBSERVACION_SISTEMA") + 1
        idx_obs_auditor = _COLUMNAS_CONTROL_XLSX.index("OBSERVACION_AUDITOR") + 1
        indices_importe = [
            idx for idx, col in enumerate(_COLUMNAS_CONTROL_XLSX, start=1) if col in _COLUMNAS_IMPORTE_XLSX
        ]

        for fila_idx in range(2, ultima_fila + 1):
            for idx in indices_importe:
                ws.cell(row=fila_idx, column=idx).number_format = "#,##0.00"

            ws.cell(row=fila_idx, column=idx_obs_sistema).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(row=fila_idx, column=idx_obs_auditor).alignment = Alignment(wrap_text=True, vertical="top")

            celda_estado = ws.cell(row=fila_idx, column=idx_estado)
            if celda_estado.value == _ESTADO_ABIERTO:
                celda_estado.fill = _RELLENO_ABIERTO
                celda_estado.font = _FUENTE_ABIERTO
            elif celda_estado.value == _ESTADO_CERRADO:
                celda_estado.fill = _RELLENO_CERRADO
                celda_estado.font = _FUENTE_CERRADO
            elif celda_estado.value == _ESTADO_REVISAR:
                celda_estado.fill = _RELLENO_REVISAR
                celda_estado.font = _FUENTE_REVISAR
            elif celda_estado.value == _ESTADO_CERRADO_MANUALMENTE:
                celda_estado.fill = _RELLENO_CERRADO_MANUALMENTE
                celda_estado.font = _FUENTE_CERRADO_MANUALMENTE

    ruta_tmp = f"{ruta}.tmp"
    wb.save(ruta_tmp)
    os.replace(ruta_tmp, ruta)


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def ejecutar_control(ruta_global, ruta_historico, nombre_archivo_global=None,
                      ruta_salida_xlsx=None, ruta_salida_json=None,
                      ruta_observaciones_json=None, dry_run=False):
    if not ruta_global or not os.path.isfile(ruta_global):
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_NO_ENCONTRADO"], "ruta_global": ruta_global}

    nombre_archivo_global = nombre_archivo_global or os.path.basename(ruta_global)
    sha_actual = _hash_archivo(ruta_global)

    periodo = _derivar_periodo(nombre_archivo_global)
    if periodo is None:
        return {
            "estado": "ERROR_TECNICO",
            "problemas": ["GLOBAL_NOMBRE_NO_CANONICO"],
            "archivo_global": nombre_archivo_global,
            "sha256_global": sha_actual,
            "mensaje": (
                f"'{nombre_archivo_global}' no sigue la convención canónica "
                "SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx; no se puede derivar el "
                "periodo de forma segura. El control se detiene sin leer "
                "partidas ni tocar HISTORICO/XLSX/JSON."
            ),
        }

    historico = cargar_historico(ruta_historico)
    libro_periodos = _cargar_libro_periodos(ruta_historico)
    ahora = datetime.datetime.now().isoformat(timespec="seconds")

    estado_idemp = _estado_idempotencia(historico, libro_periodos, periodo, sha_actual)

    if estado_idemp == "RECUPERAR_APLICADO":
        # El registro quedó en PENDIENTE pero el histórico YA refleja
        # este periodo+SHA (corte a mitad de camino DESPUÉS de escribir
        # el histórico y ANTES de sellar APLICADO). Se sella APLICADO
        # ahora, sin reacumular nada.
        if not dry_run:
            libro_periodos[periodo] = {
                "sha256_global": sha_actual, "estado": _PERIODO_APLICADO,
                "fecha_ejecucion": ahora, "recuperado": True,
            }
            _guardar_libro_periodos(ruta_historico, libro_periodos)
        estado_idemp = "YA_PROCESADO_SIN_CAMBIOS"
    elif estado_idemp == "RECUPERAR_PENDIENTE":
        # El registro quedó en PENDIENTE y el histórico TODAVÍA no
        # refleja este periodo+SHA (corte ANTES de escribir el
        # histórico, o antes de que la marca PENDIENTE llegara a
        # escribirse en una corrida previa). Es seguro reprocesar de
        # cero: el histórico no tiene esos importes todavía.
        estado_idemp = None

    if estado_idemp == "GLOBAL_MODIFICADO_REQUIERE_REVISION":
        return {
            "estado": estado_idemp,
            "periodo": periodo,
            "archivo_global": nombre_archivo_global,
            "sha256_global": sha_actual,
            "mensaje": (
                "Ya existe un histórico para este periodo con un SHA-256 de "
                "GLOBAL distinto al actual. No se modifica el histórico "
                "automáticamente: requiere decisión humana."
            ),
            "dry_run": dry_run,
            "historico_actualizado": False,
            "archivo_control_xlsx": None,
        }

    if estado_idemp == "YA_PROCESADO_SIN_CAMBIOS":
        observaciones_aplicadas = 0
        problemas_obs = []
        historico_modificado = False

        if ruta_observaciones_json:
            datos_obs = cargar_json(ruta_observaciones_json)
            if datos_obs is None:
                problemas_obs = ["OBSERVACIONES_JSON_NO_LEGIBLE_O_INEXISTENTE"]
            else:
                ok, problemas_obs, observaciones_aplicadas = aplicar_observaciones(
                    datos_obs, periodo, sha_actual, historico, ahora
                )
                historico_modificado = ok and observaciones_aplicadas > 0

        resumen = {
            "estado": estado_idemp,
            "periodo": periodo,
            "archivo_global": nombre_archivo_global,
            "sha256_global": sha_actual,
            "mensaje": "Este periodo ya fue acumulado con este mismo GLOBAL. No se vuelve a acumular.",
            "dry_run": dry_run,
            "observaciones_aplicadas": observaciones_aplicadas,
            "problemas_observaciones_json": problemas_obs,
            "historico_actualizado": False,
            "archivo_control_xlsx": None,
        }

        if historico_modificado and not dry_run:
            guardar_historico(ruta_historico, historico)
            resumen["historico_actualizado"] = True
            if ruta_salida_xlsx:
                filas_excel = _construir_filas_excel(historico, {}, periodo)
                guardar_control_xlsx(ruta_salida_xlsx, filas_excel)
                resumen["archivo_control_xlsx"] = ruta_salida_xlsx
            if ruta_salida_json:
                with open(ruta_salida_json, "w", encoding="utf-8") as f:
                    json.dump(resumen, f, ensure_ascii=False, indent=2)
        return resumen

    # --- Camino normal: primera vez que se acumula este periodo+SHA. ---
    try:
        partidas = leer_partidas_global(ruta_global)
    except HojaNoEncontradaError:
        return {"estado": "ERROR_TECNICO", "problemas": ["GLOBAL_HOJA_1_NO_ENCONTRADA"],
                "archivo_global": nombre_archivo_global, "sha256_global": sha_actual}
    except Exception as exc:  # noqa: BLE001 — GLOBAL ilegible, se reporta y se detiene
        return {"estado": "ERROR_TECNICO", "problemas": [f"GLOBAL_ILEGIBLE:{exc}"],
                "archivo_global": nombre_archivo_global, "sha256_global": sha_actual}

    candidatas, faltantes = clasificar_partidas(partidas)
    grupos_mes = agrupar_movimientos_mes(candidatas)

    claves = sorted(set(historico.keys()) | set(grupos_mes.keys()))
    nuevo_historico = {}
    for clave in claves:
        cuenta, _asignacion = clave
        tipo_cuenta, tipo_label = _CUENTAS_CONTROL[cuenta]
        prev_row = historico.get(clave)
        mov = grupos_mes.get(clave)
        debe_mes = mov["debe"] if mov else Decimal("0.00")
        haber_mes = mov["haber"] if mov else Decimal("0.00")
        nuevo_historico[clave] = _actualizar_fila(
            clave, tipo_cuenta, tipo_label, prev_row, debe_mes, haber_mes, periodo, sha_actual, ahora,
        )

    observaciones_aplicadas = 0
    problemas_obs = []
    if ruta_observaciones_json:
        datos_obs = cargar_json(ruta_observaciones_json)
        if datos_obs is None:
            problemas_obs = ["OBSERVACIONES_JSON_NO_LEGIBLE_O_INEXISTENTE"]
        else:
            _ok, problemas_obs, observaciones_aplicadas = aplicar_observaciones(
                datos_obs, periodo, sha_actual, nuevo_historico, ahora
            )

    abiertas = sum(1 for f in nuevo_historico.values() if f["estado"] == _ESTADO_ABIERTO)
    cerradas = sum(1 for f in nuevo_historico.values() if f["estado"] == _ESTADO_CERRADO)
    revisar = sum(1 for f in nuevo_historico.values() if f["estado"] == _ESTADO_REVISAR)

    resumen = {
        "estado": "OK",
        "periodo": periodo,
        "archivo_global": nombre_archivo_global,
        "sha256_global": sha_actual,
        "fecha_ejecucion": ahora,
        "cuentas_evaluadas": len({cuenta for cuenta, _a in grupos_mes.keys()}),
        "llaves_evaluadas": len(grupos_mes),
        "abiertas": abiertas,
        "cerradas": cerradas,
        "revisar": revisar,
        "asignaciones_faltantes": len(faltantes),
        "detalle_asignaciones_faltantes": faltantes,
        "observaciones_aplicadas": observaciones_aplicadas,
        "problemas_observaciones_json": problemas_obs,
        "dry_run": dry_run,
        "historico_actualizado": False,
        "archivo_control_xlsx": None,
        "archivo_control_json": None,
    }

    if not dry_run:
        # Mecanismo PENDIENTE -> escritura atómica del histórico -> APLICADO:
        # el libro de periodos es la fuente autoritativa. PENDIENTE se
        # escribe ANTES de tocar el histórico; APLICADO se sella DESPUÉS
        # de que el histórico ya quedó escrito — así _estado_idempotencia
        # puede distinguir de forma segura, ante un corte a mitad de
        # camino, si el histórico llegó a escribirse o no (ver
        # RECUPERAR_APLICADO/RECUPERAR_PENDIENTE más arriba).
        libro_periodos[periodo] = {
            "sha256_global": sha_actual, "estado": _PERIODO_PENDIENTE, "fecha_inicio": ahora,
        }
        _guardar_libro_periodos(ruta_historico, libro_periodos)

        guardar_historico(ruta_historico, nuevo_historico)

        libro_periodos[periodo] = {
            "sha256_global": sha_actual, "estado": _PERIODO_APLICADO, "fecha_ejecucion": ahora,
        }
        _guardar_libro_periodos(ruta_historico, libro_periodos)
        resumen["historico_actualizado"] = True
        if ruta_salida_xlsx:
            filas_excel = _construir_filas_excel(nuevo_historico, grupos_mes, periodo, faltantes)
            guardar_control_xlsx(ruta_salida_xlsx, filas_excel)
            resumen["archivo_control_xlsx"] = ruta_salida_xlsx
        if ruta_salida_json:
            resumen["archivo_control_json"] = ruta_salida_json
            with open(ruta_salida_json, "w", encoding="utf-8") as f:
                json.dump(resumen, f, ensure_ascii=False, indent=2)

    return resumen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--global", dest="ruta_global", required=True,
                         help="Ruta local al SAP GLOBAL (.xlsx) del mes (ya generado por "
                              "consolidador_mensual.py, posterior a CONTROL 1). Solo lectura.")
    parser.add_argument("--historico", dest="ruta_historico", required=True,
                         help="Ruta local a HISTORICO_CXC_CXP.csv (se crea si no existe).")
    parser.add_argument("--nombre-archivo", dest="nombre_archivo_global", default=None,
                         help="Nombre a registrar como archivo_global (por defecto, basename de --global). "
                              "Debe seguir SAP_GLOBAL_TIQ_<MES>_<AÑO>.xlsx.")
    parser.add_argument("--salida-xlsx", dest="ruta_salida_xlsx", required=True,
                         help="Ruta donde escribir CONTROL_CXC_CXP_<MES>_<AÑO>.xlsx.")
    parser.add_argument("--salida-json", dest="ruta_salida_json", required=True,
                         help="Ruta donde escribir CONTROL_CXC_CXP_<MES>_<AÑO>.json.")
    parser.add_argument("--observaciones-json", dest="ruta_observaciones_json", default=None,
                         help="Ruta a un JSON PUENTE (formato "
                              "CONTROL_CXC_CXP_<MES>_<AÑO>_OBSERVACIONES.json) generado por Cowork a "
                              "partir de lo leído del .xlsx en Drive. El auditor nunca lo edita. Solo "
                              "puede actualizar OBSERVACION_AUDITOR de llaves CUENTA+ASIGNACION ya "
                              "existentes en el histórico; nunca crea llaves ni toca saldos/estados/"
                              "importes/asignaciones/cuentas.")
    parser.add_argument("--dry-run", action="store_true",
                         help="No modifica el histórico, no genera/reemplaza xlsx ni json; "
                              "solo calcula y reporta qué ocurriría.")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    resumen = ejecutar_control(
        ruta_global=args.ruta_global,
        ruta_historico=args.ruta_historico,
        nombre_archivo_global=args.nombre_archivo_global,
        ruta_salida_xlsx=args.ruta_salida_xlsx,
        ruta_salida_json=args.ruta_salida_json,
        ruta_observaciones_json=args.ruta_observaciones_json,
        dry_run=args.dry_run,
    )
    print(json.dumps(resumen, ensure_ascii=False))
    return 0 if resumen.get("estado") != "ERROR_TECNICO" else 1


if __name__ == "__main__":
    raise SystemExit(main())

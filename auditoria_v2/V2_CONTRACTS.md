# V2_CONTRACTS.md — Contratos funcionales V2 → V3

Comportamientos que **V3 no puede romper** sin decisión humana explícita. Cada contrato indica
el componente V2 que lo implementa hoy, el test que lo protege, entrada/resultado esperado,
riesgo si se rompe y criticidad. Fuente completa de reglas: `V2_BUSINESS_RULES.csv`.

---

### CONTRACT-001 — Exclusión de ALQUILERES
**Descripción:** Toda línea CI con `banco == ALQUILERES` se excluye del asiento y del universo
de cuadre; se conserva agregada por SFC para ajustar el HABER.
**Componente V2:** `motor_tiquipaya.validar_ci()` / `_detalle_para_asiento()`.
**Test:** `tests/test_cruces.py`, `tests/test_asiento.py`.
**Entrada:** CI con `banco` normalizado a `"ALQUILERES"`.
**Resultado esperado:** partida ALQUILERES nunca aparece en `asiento["partidas"]`;
`HABER SFCxxx = TOTAL SFCxxx − ALQUILERES de ese SFC`.
**Riesgo si V3 lo rompe:** partidas contables incorrectas, universo de cuadre alterado.
**Criticidad:** CRÍTICA.

### CONTRACT-002 — Comisión ATC: 110201003 vs 110201008, prohibición NO global
**Descripción:** La cuenta `110201003` es válida para cualquier partida excepto si esa partida
tiene `origen == "ATC_COMISION"`, en cuyo caso debe ser `110201008`.
**Componente V2:** `motor_tiquipaya._validar_partidas()`, `sap_writer._validar_precondiciones()`
(defensa en profundidad, intencional).
**Test:** `tests/test_asiento.py`, `tests/test_sap.py`.
**Entrada:** partida con `origen="ATC_COMISION"` y `cuenta_mayor` arbitraria.
**Resultado esperado:** `ATC_COMISION_CUENTA_INVALIDA`/`ATC_COMISION_CUENTA_PROHIBIDA` solo si
`cuenta_mayor != 110201008`; una CI legítima con cuenta `110201003` **nunca** se bloquea.
**Riesgo si V3 lo rompe:** o se aceptan comisiones ATC mal contabilizadas, o se bloquean CI
legítimas — verificado explícitamente que V2 NO implementa esto de forma excesivamente amplia.
**Criticidad:** CRÍTICA.

### CONTRACT-003 — Cuadre: Cargo = Haber siempre que hay asiento
**Descripción:** Un asiento con `estado="OK"` implica `total_cargo == total_haber` y
`diferencia == 0.00`; si no, `estado="ERROR"` y `partidas=[]` (nunca partidas inválidas
utilizables).
**Componente V2:** `motor_tiquipaya._validar_partidas()`.
**Test:** `tests/test_asiento.py`.
**Riesgo si V3 lo rompe:** asientos desbalanceados llegarían a SAP.
**Criticidad:** CRÍTICA.

### CONTRACT-004 — Reglas SAP: columnas autorizadas y plantilla inmutable
**Descripción:** Solo se escriben las columnas B,C,D,E,F,L,O,R,U,V,W (partidas) /
B,C,D,E,F,G,H,L (cabecera); la plantilla original nunca se abre en modo escritura (verificado
por hash antes/después); el SAP generado se relee de disco para validar (nunca se confía en
memoria).
**Componente V2:** `sap_writer.py` completo.
**Test:** `tests/test_sap.py` (30 tests).
**Riesgo si V3 lo rompe:** corrupción silenciosa de la plantilla maestra, o SAP con columnas
fuera de contrato que SAP real podría rechazar o malinterpretar.
**Criticidad:** CRÍTICA.

### CONTRACT-005 — Original `.xlsm` inmutable
**Descripción:** El CIERRE original nunca se abre en modo escritura; toda corrección se aplica
sobre una copia profunda en memoria.
**Componente V2:** `excel_io.leer_cierre()` (siempre `read_only=True`),
`correcciones_tiquipaya.aplicar_correccion_en_memoria()` (`deepcopy`).
**Test:** `tests/test_correcciones_tiquipaya.py`.
**Riesgo si V3 lo rompe:** pérdida de la fuente de verdad auditable de un cierre.
**Criticidad:** CRÍTICA.

### CONTRACT-006 — Correcciones autorizadas: campos permitidos, importes nunca
**Descripción:** Solo son corregibles CI.`cuenta_contable`/`asignacion`;
VOUCHER.`codigo_informado` (únicamente entre los candidatos que el motor ya propuso);
ATC.`neto_cuenta_contable`/`neto_asignacion`/`comision_cuenta_contable`/`comision_asignacion`
(solo modo PRECONCILIADO). Ningún importe es corregible.
**Componente V2:** `correcciones_tiquipaya.CAMPOS_CORREGIBLES`, `validar_schema_correccion()`.
**Test:** `tests/test_correcciones_tiquipaya.py` (17 tests).
**Riesgo si V3 lo rompe:** permitir corregir importes anularía la garantía de que el motor
Python es la única autoridad contable determinística.
**Criticidad:** CRÍTICA.
**Nota de discrepancia:** `HANDOFF_CODE_V2.md` §16.3 documenta `glosa` como campo corregible de
CI; el código (fuente real) no lo incluye. Ver `V2_OPTIMIZATION_MATRIX.csv` OPT-006 — es deuda
documental, no una ambigüedad del contrato en sí (el contrato vigente es el del código).

### CONTRACT-007 — Prohibición de correcciones libres de importe
**Descripción:** Ningún flujo de corrección (Excel/JSON de CONTROL 1, `--revision-json`, FASE 3)
permite tocar un importe. Ver también CONTRACT-006.
**Componente V2:** `correcciones_tiquipaya.py`, `control_asignaciones.py` (solo corrige columna
R/Asignación).
**Test:** `tests/test_correcciones_tiquipaya.py`, `tests/test_control_asignaciones.py`.
**Criticidad:** CRÍTICA.

### CONTRACT-008 — Idempotencia por SHA256 (nunca por nombre de archivo)
**Descripción:** `HashOrigen` (SHA256 del `.xlsm`) es la única llave de idempotencia; el nombre
de archivo nunca es suficiente por sí solo.
**Componente V2:** `pipeline_tiquipaya.calcular_sha256()`, `nombre_marcador_procesado()`.
**Test:** `tests/test_pipeline_tiquipaya.py`, `tests/test_run_batch.py`.
**Resultado esperado:** un reintento con el mismo SHA256 devuelve `YA_PROCESADO`.
**Riesgo si V3 lo rompe:** duplicación de asientos/publicaciones.
**Criticidad:** CRÍTICA.

### CONTRACT-009 — Marcador inmutable `PROCESADO_<SHA256>.json`
**Descripción:** Único control operativo de producción (el CSV es legacy/fallback); solo se
construye tras 4 confirmaciones explícitas de publicación; nunca al terminar el motor.
**Componente V2:** `pipeline_tiquipaya.construir_marcador_procesado()`, `publicar_cierre.py`.
**Test:** `tests/test_pipeline_tiquipaya.py`, `tests/test_publicar_cierre.py`.
**Riesgo si V3 lo rompe:** pérdida del control de idempotencia productivo real.
**Criticidad:** CRÍTICA.

### CONTRACT-010 — Búsqueda EXACTA del cierre (REGLA G)
**Descripción:** 1 coincidencia exacta de nombre → se usa; 0 → `CIERRE_NO_LOCALIZADO_EN_00_ENTRADA`;
>1 → `CIERRE_AMBIGUO_EN_00_ENTRADA`. Nunca "tomar el primer resultado".
**Componente V2:** nodos Google Drive + IF del workflow n8n `LkS0RHu9KEbHCR4p`.
**Test:** ninguno automatizado (vive en n8n, sin harness de test en este repo — ver
`V2_TEST_AUDIT.csv` T-021).
**Riesgo si V3 lo rompe:** repetir el incidente real ya documentado (cierre 09 tomado
incorrectamente entre 11/10/09).
**Criticidad:** CRÍTICA. **Evidencia:** `REQUIERE_VALIDACION_HUMANA` (ver limitación en
`V2_SYSTEM_MAP.md` §9 — no se releyó el parámetro exacto de cada nodo Drive).

### CONTRACT-011 — Publicación controlada / separación procesar-publicar
**Descripción:** `procesar_cierre_completo()`/`procesar_cierre_con_correccion()` nunca marcan
PROCESADO ni publican; un cierre `BLOQUEADO`/`ERROR` nunca llega a la rama de publicación.
**Componente V2:** `pipeline_tiquipaya.py` + workflow n8n (rama `DECIDIR - Estado del cierre`).
**Test:** `tests/test_pipeline_tiquipaya.py`.
**Criticidad:** CRÍTICA.

### CONTRACT-012 — Estados de revisión (`ERROR_REVISAR` es reversible, no terminal)
**Descripción:** Un cierre en `ERROR_REVISAR` puede pasar a `LISTO_PARA_PUBLICAR` solo a través
de una corrección autorizada y reprocesada (FASE 3 Parte B), nunca automáticamente.
**Componente V2:** `pipeline_tiquipaya.procesar_cierre_con_correccion()`.
**Test:** `tests/test_correcciones_tiquipaya.py`.
**Criticidad:** ALTA.

### CONTRACT-013 — Trazabilidad sin sobrescritura (REPROCESOS/ separado)
**Descripción:** `RESULTADO_TIQ_<fecha>.json` y el SAP originales nunca se sobrescriben; todo
reproceso escribe a rutas nuevas dentro de `REPROCESOS/`.
**Componente V2:** `aplicar_correccion.py::_rutas_reproceso()`.
**Test:** `tests/test_correcciones_tiquipaya.py` (indirecto, vía `pipeline`); el CLI en sí no
tiene test dedicado (ver `V2_RISKS.csv` RISK-004).
**Criticidad:** ALTA.

### CONTRACT-014 — Cierre ya publicado nunca admite corrección nueva
**Descripción:** Si existe `PROCESADO_<hash>.json` para un cierre, cualquier corrección nueva se
rechaza con `CIERRE_YA_PUBLICADO_NO_CORREGIBLE`.
**Componente V2:** `pipeline_tiquipaya.procesar_cierre_con_correccion()`, `aplicar_correccion.py`.
**Test:** `tests/test_correcciones_tiquipaya.py`.
**Criticidad:** CRÍTICA.

### CONTRACT-015 — CONTROL 1: corrección todo-o-nada sobre el GLOBAL, solo columna R
**Descripción:** El GLOBAL es de solo lectura mientras haya alertas de duplicado sin validar;
la corrección solo se aplica cuando el 100% de las alertas del periodo están resueltas, y
verificando célula por célula antes de escribir; si una falla, no se escribe ninguna.
**Componente V2:** `control_asignaciones.aplicar_correcciones_global()`.
**Test:** `tests/test_control_asignaciones.py` (64 tests).
**Criticidad:** CRÍTICA.

### CONTRACT-016 — Ninguna IA decide resultados contables determinísticos
**Descripción:** Cuentas, importes, conciliaciones, SAP, asignaciones, exclusiones, cuadres y
clasificaciones contables son siempre determinísticas, verificables, testeables y auditables en
Python puro. Confirmado por lectura de los 11 módulos: cero imports de SDKs de LLM en código de
producción; el panel "Asistente de análisis" del mockup de FASE 3 está explícitamente
deshabilitado (HANDOFF §16.2).
**Componente V2:** todo `motor_tiquipaya.py`, `sap_writer.py`, `control_*.py`.
**Test:** toda la suite (432 tests).
**Riesgo si V3 lo rompe:** pérdida de determinismo/auditabilidad contable — es la condición de
diseño no negociable de todo el proyecto.
**Criticidad:** CRÍTICA (principio rector, no solo una regla puntual).

### CONTRACT-017 — Idempotencia CONTROL 3: periodo+SHA, nunca campos mutables
**Descripción:** La idempotencia de un periodo nunca se decide con `sha256_global_ultimo`
(mutable); se usa exclusivamente `HISTORICO_CXC_CXP_PERIODOS.json` con transacción de 2 fases
PENDIENTE→APLICADO. Protege un bug real ya corregido (ver `V2_BUSINESS_RULES.csv` BR-020).
**Componente V2:** `control_cxc_cxp._estado_idempotencia()`.
**Test:** `tests/test_control_cxc_cxp.py::TestConsistenciaHistoricoPeriodos` (5 tests).
**Criticidad:** CRÍTICA — es una regresión real ya vivida, no solo una regla teórica.

### CONTRACT-018 — Autocorrección VOUCHER limitada a 0↔O
**Descripción:** La única autocorrección automática de código de asignación es el intercambio
`0`↔`O`, y solo si produce un candidato único; cualquier otra variación de 1-2 caracteres
(`POSIBLE_TYPO`) queda bloqueante, nunca se autocorrige.
**Componente V2:** `motor_tiquipaya._variantes_0_o()`, `_clasificar_voucher()`.
**Test:** `tests/test_cruces.py`.
**Criticidad:** ALTA.

---

**Uso previsto:** estos 18 contratos son el criterio mínimo de equivalencia funcional entre V2 y
V3. Ningún cambio de arquitectura propuesto en `V3_ARCHITECTURE_PROPOSAL.md` puede romper uno de
estos contratos sin que el documento lo señale explícitamente como `HUMAN_DECISION_REQUIRED`.

# V3_ARCHITECTURE_PROPOSAL.md — Propuesta técnica basada en la auditoría de V2

**`V3_PLAN.md` no existe en el repositorio** (búsqueda exhaustiva `find / -iname "V3_PLAN.md"`
sin resultados). Por lo tanto no hay una propuesta previa que comparar/contrastar; esta sección
del encargo (§19) queda documentada como **no aplicable por ausencia del archivo**, no omitida.

Esta propuesta parte del V2 existente (ver `V2_TO_V3_MASTER.csv` para el detalle nodo por nodo)
y no diseña nada "desde cero": para cada componente indica su estado actual, el problema
identificado (con evidencia), la responsabilidad propuesta en V3, y la clasificación de acción.

---

## 1. Principio rector (no negociable, ver CONTRACT-016)

V3 sigue siendo **Python determinístico + orquestador ligero**. Ninguna propuesta de esta
sección introduce IA en el camino de decisión contable. Donde se menciona IA (p. ej. asistir al
auditor a interpretar excepciones) es siempre explicación/resumen posterior a una decisión ya
tomada de forma determinística — igual que el panel "Asistente de análisis" ya deshabilitado en
el mockup de FASE 3.

## 2. Mapa de decisiones por área

### 2.1 Ingesta (lectura de CIERRE/MAESTRO/PLANTILLA)

- **V2 component:** `excel_io.py`.
- **Responsabilidad actual:** lectura SOLO LECTURA vía openpyxl, normalización, indexado en
  memoria.
- **Problema identificado:** ninguno funcional. Deuda menor: sin test unitario propio dedicado
  (se ejercita indirectamente vía `motor_tiquipaya`/fixtures).
- **V3 proposed responsibility:** idéntica.
- **Clasificación:** **KEEP**.
- **Estrategia de migración:** `REUSE_AS_IS`.
- **Razón:** módulo pequeño, bien acotado, con contrato claro (CONTRACT-005) y 100% determinístico.
- **Evidencia:** `V2_NODES.csv` PY-EXCELIO-*.
- **Riesgo:** bajo si no se toca.
- **Dependencia:** ninguna externa a `openpyxl`.
- **Tests que lo protegen:** indirectos, vía `test_pipeline_tiquipaya.py`/`test_asiento.py`.
- **Requiere decisión de negocio:** No.

### 2.2 Preparación / normalización + motor Python (cruces, cuadre, asiento)

- **V2 component:** `motor_tiquipaya.py` completo.
- **Responsabilidad actual:** ETAPAS 1-5, corazón contable.
- **Problema identificado:** ninguno funcional (110+ tests, comportamiento validado con
  regresión sintética real). `ejecutar_lote_v2()` existe pero no está integrada al runner
  productivo (procesamiento repetido de apertura de maestro, ver OPT-002).
- **V3 proposed responsibility:** idéntica en reglas; integrar `ejecutar_lote_v2()` al runner
  para eliminar la reapertura redundante del maestro por cada cierre del batch.
- **Clasificación:** **KEEP** (reglas) + **REFACTOR** (integración del batch, no la lógica en sí).
- **Estrategia de migración:** `REUSE_AS_IS` para las reglas; `REFACTOR_LATER` para el cableado
  batch.
- **Razón:** el riesgo de tocar reglas contables ya validadas es inaceptable sin beneficio
  claro; el riesgo de cablear el batch existente es acotado y ya tiene la función lista.
- **Evidencia:** `V2_OPTIMIZATION_MATRIX.csv` OPT-002.
- **Riesgo:** MUY_ALTO tocar reglas; MEDIO tocar el cableado batch.
- **Dependencia:** `pipeline_tiquipaya.procesar_cierre_completo` asume hoy una apertura por
  llamada — habría que adaptar esa interfaz o crear una variante batch explícita.
- **Tests que lo protegen:** toda la suite de motor + `test_run_batch.py`.
- **Requiere decisión de negocio:** No (es una optimización de rendimiento, no de reglas).

### 2.3 Clasificación de estado del cierre

- **V2 component:** `motor_tiquipaya._ejecutar_v2_sobre_cierre()` (estado) + n8n
  `DECIDIR - Estado del cierre` (enrutamiento).
- **Problema identificado:** ninguno. La prioridad conservadora (ERROR TECNICO > REVISAR > OK >
  SIN ACCION) está documentada y testeada.
- **V3 proposed responsibility:** idéntica.
- **Clasificación:** **KEEP**.
- **Estrategia de migración:** `REUSE_AS_IS` (Python) / `KEEP_IN_N8N` (el switch de enrutamiento,
  si V3 sigue usando un orquestador tipo n8n) o `MOVE_TO_PYTHON` si V3 decide que el
  orquestador deje de tomar ninguna decisión de negocio y solo reciba un estado ya resuelto por
  Python (el estado YA es resuelto por Python hoy; el switch de n8n solo enruta, no reclasifica).
- **Riesgo:** bajo (es una regla ya centralizada en Python; n8n no reinterpreta nada).
- **Requiere decisión de negocio:** No.

### 2.4 Revisión

- **V2 component:** n8n rama REVISAR (`Wait+Form`, hoy de solo lectura) +
  `n8n_frontend/revision_correccion.html` (`GET /datos`).
- **Problema identificado:** HANDOFF §16.4 ya documenta que el nodo `CONFIRMAR - Revision de
  excepciones` "deja de ser donde se decide" con FASE 3 activa, pero el re-wire formal (qué nodo
  apunta a qué) sigue pendiente según el propio documento — confirmado que la implementación de
  FASE 3 ya existe, pero no se verificó si ese re-wire puntual del nodo Wait/Form ya se hizo.
- **V3 proposed responsibility:** el nodo Wait/Form pasa a ser un resumen + enlace al módulo de
  corrección (ya diseñado, posiblemente ya implementado — **requiere verificación humana
  puntual de ese nodo específico**, ver limitación en `V2_SYSTEM_MAP.md`).
- **Clasificación:** **REFACTOR** (del wiring, no de la lógica Python).
- **Estrategia de migración:** `KEEP_IN_N8N` si V3 sigue usando n8n; `HUMAN_DECISION_REQUIRED`
  sobre si vale la pena mantener el Wait/Form en absoluto una vez existe el frontend HTML.
- **Riesgo:** medio (zona de UX, no de contabilidad).
- **Tests que lo protegen:** ninguno automatizado (n8n sin harness).
- **Requiere decisión de negocio:** Sí — decidir si el Wait/Form nativo se retira en V3 a favor
  exclusivo del frontend HTML.

### 2.5 Corrección (FASE 3 Parte B)

- **V2 component:** `correcciones_tiquipaya.py`, `aplicar_correccion.py`,
  `pipeline_tiquipaya.procesar_cierre_con_correccion()`.
- **Problema identificado:** sin test dedicado del CLI (`aplicar_correccion.py`); discrepancia
  documental HANDOFF vs código sobre el campo `glosa` (OPT-006).
- **V3 proposed responsibility:** idéntica; cerrar el gap de test antes de dar por completada la
  migración.
- **Clasificación:** **KEEP**.
- **Estrategia de migración:** `REUSE_AS_IS`, con `RETIRE_AFTER_PARITY` para el CSV legacy de
  control (`CONTROL_PROCESAMIENTO.csv`, ver 2.8) una vez confirmado que nada externo lo usa.
- **Riesgo:** bajo (bien acotado, reglas claras — CONTRACT-006/007).
- **Requiere decisión de negocio:** No para la lógica; Sí para decidir si `glosa` se vuelve
  corregible (ver CONTRACT-006).

### 2.6 Publicación

- **V2 component:** dos implementaciones n8n paralelas (single vía aprobación individual, y
  múltiple vía `/publicar-listos`), ambas convergiendo en `publicar_cierre.py`.
- **Problema identificado:** duplicación de wiring n8n (RISK-005/OPT-003); confirmaciones de
  publicación hardcodeadas a `true` en el Execute Command, dependientes del orden visual del
  canvas más que de una verificación explícita (RISK-003).
- **V3 proposed responsibility:** una sola implementación de "publicar N cierres" (N≥1) que
  derive cada confirmación del resultado real de la operación Drive correspondiente, no de un
  literal.
- **Clasificación:** **MERGE** (las dos ramas de publicación en una).
- **Estrategia de migración:** `KEEP_IN_N8N` para la orquestación Drive, `WRAP` alrededor de
  `publicar_cierre.py` (que en sí mismo se mantiene `REUSE_AS_IS`).
- **Riesgo:** alto tocar esta zona sin pruebas exhaustivas (CONTRACT-011); requiere plan de
  pruebas manual explícito antes de tocar el canvas.
- **Tests que lo protegen:** `test_pipeline_tiquipaya.py`, `test_publicar_cierre.py` (la lógica
  Python); ninguno para el wiring n8n en sí.
- **Requiere decisión de negocio:** Sí — el usuario debe validar que unificar las dos ramas no
  cambia el comportamiento observable para el auditor.

### 2.7 Auditoría (CONTROL 1 / CONTROL 3 / consolidador mensual)

- **V2 component:** `consolidador_mensual.py`, `control_asignaciones.py`, `control_cxc_cxp.py`.
- **Problema identificado:** ninguno funcional; son los módulos más nuevos y mejor
  documentados (HANDOFF §§13-15), con la mayor densidad de tests (169 tests combinados).
- **V3 proposed responsibility:** idéntica.
- **Clasificación:** **KEEP**.
- **Estrategia de migración:** `REUSE_AS_IS`.
- **Riesgo:** bajo si no se tocan; el propio HANDOFF documenta un bug real ya corregido en
  CONTROL 3 (CONTRACT-017) — valioso como caso de regresión a nunca reintroducir.
- **Requiere decisión de negocio:** No.

### 2.8 Control de procesamiento legacy (CSV)

- **V2 component:** `pipeline_tiquipaya.registrar_procesado()` / `CONTROL_PROCESAMIENTO.csv`.
- **Problema identificado:** código y tests completos, pero **sin llamador productivo activo
  detectado** (`run_batch.py` siempre pasa `ruta_control=None`).
- **V3 proposed responsibility:** ninguna, salvo que se confirme un consumidor externo
  (Cowork o la Skill `auditor-caja-tiquipaya`, mencionada en HANDOFF pero fuera de este repo).
- **Clasificación:** **DEPRECATE** (condicional).
- **Estrategia de migración:** `RETIRE_AFTER_PARITY` — solo después de confirmar con el usuario.
- **Riesgo:** bajo mantenerlo; riesgo de romper un consumidor externo desconocido si se retira
  sin confirmar.
- **Requiere decisión de negocio:** **Sí, explícitamente** (`HUMAN_DECISION_REQUIRED`).

### 2.9 Frontend

- **V2 component:** `n8n_frontend/revision_correccion.html`.
- **Problema identificado:** sin test automatizado; sin autenticación (por diseño, diferido).
- **V3 proposed responsibility:** idéntica en forma (SPA estática, sin build, rutas relativas —
  principio ya validado y correcto para portabilidad); agregar autenticación básica en los
  endpoints que mutan estado antes de cualquier despliegue fuera de un entorno de desarrollo
  controlado.
- **Clasificación:** **KEEP** (arquitectura) + **REFACTOR** (autenticación).
- **Estrategia de migración:** `REUSE_AS_IS` + `WRAP` (capa de auth alrededor de los webhooks).
- **Riesgo:** el de NO hacerlo es alto si se expone fuera del Codespace (RISK-001).
- **Requiere decisión de negocio:** Sí — qué mecanismo de auth (HTTP Basic, header token, otro).

### 2.10 Infraestructura (n8n, Execute Command, rutas)

- **V2 component:** `scripts/start_n8n.sh`, nodos `executeCommand` del workflow.
- **Problema identificado:** `NODES_EXCLUDE=[]` habilita Execute Command a nivel de **instancia**
  n8n (no por workflow); comandos interpolan campos de webhooks sin auth (RISK-001); rutas
  absolutas hardcodeadas del POC (RISK-006).
- **V3 proposed responsibility:** aislar cualquier ejecución de comandos en un wrapper que
  valide/escape argumentos (o use `argv` sin shell), y parametrizar toda ruta vía variables de
  entorno — mismo patrón ya usado para `N8N_EDITOR_BASE_URL`/`WEBHOOK_URL`.
- **Clasificación:** **REFACTOR**.
- **Estrategia de migración:** `WRAP`.
- **Riesgo:** el de no hacerlo (P0 fuera del Codespace) supera ampliamente el riesgo de hacerlo.
- **Requiere decisión de negocio:** No técnicamente, pero sí de priorización (P0/P1).

## 3. Resumen de clasificación (todos los componentes)

Ver `V2_TO_V3_MASTER.csv` (197 filas) para el detalle nodo por nodo con
`recommended_v3_action`/`v3_migration_strategy`/`priority` ya asignados de forma consistente con
esta narrativa.

## 4. Documentación a corregir antes de iniciar V3

`HANDOFF_CODE_V2.md` §16 debe actualizarse para reflejar que FASE 3 (Parte A y B) ya está
implementada (ver `V2_RISKS.csv` RISK-002) — de lo contrario cualquier sesión futura (humana o
de IA) que use ese documento como única fuente de contexto partirá de una premisa incorrecta.
Esto no es parte de V3 en sí: es una corrección de documentación que puede hacerse sobre V2 sin
"abrir" el sistema cerrado (es texto, no código ni configuración funcional).

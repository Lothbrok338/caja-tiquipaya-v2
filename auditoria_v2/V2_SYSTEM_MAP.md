# V2_SYSTEM_MAP.md — Mapa técnico completo de CAJA TIQUIPAYA V2

Auditoría de solo lectura. Fecha: 2026-09-13. Fuente principal: **working tree actual**
(no solo el último commit Git — ver sección 0). Repositorio: `Lothbrok338/caja-tiquipaya-v2`,
ruta `/workspaces/caja-tiquipaya-v2`.

---

## 0. Estado Git y de tests (FASE 0)

```
Branch actual: main
Último commit: 17afeea "chore: add reproducible n8n startup script"
```

**Archivos modificados (no comiteados) respecto a HEAD:**
`HANDOFF_CODE_V2.md` (+222/-0), `motor_tiquipaya.py` (+185), `pipeline_tiquipaya.py` (+173),
`run_batch.py` (+3), `scripts/start_n8n.sh` (+9). Total `git diff --stat`: 5 archivos, 590
inserciones, 2 eliminaciones.

**Archivos nuevos (untracked):** `aplicar_correccion.py`, `correcciones_tiquipaya.py`,
`n8n_frontend/` (incl. `revision_correccion.html`), `publicar_cierre.py`,
`tests/test_correcciones_tiquipaya.py`, `tests/test_excepciones.py`,
`tests/test_excepciones_atc_asiento.py`, `tests/test_publicar_cierre.py`.

**`git diff --check`:** sin salida (exit 0) — sin conflictos de espacios en blanco/marcadores de
merge pendientes.

**`git log -5 --oneline --decorate`:**
```
17afeea (HEAD -> main) chore: add reproducible n8n startup script
8a5c6e8 (origin/main, origin/HEAD) Merge rama claude/loving-allen-mis635 a main (CONTROL 3: cierre manual por auditor)
8ad9a77 (origin/claude/loving-allen-mis635) CONTROL 3: test de verificación — cierre manual sobre periodo ya APLICADO
b5b3b14 CONTROL 3: cierre manual por auditor via OBSERVACION_AUDITOR
6d431ac Merge rama claude/loving-allen-mis635 a main (CONTROL 3: seguimiento acumulado CxC/CxP)
```

**Tests (`/workspaces/.venv-caja/bin/python -m pytest -q`, no el `python`/pip global —
`pytest` no está instalado en el intérprete por defecto del Codespace):**

```
432 passed in 11.84s
0 failed, 0 skipped
```

18 archivos de test, 430 funciones `def test_...` detectadas por grep (la diferencia con 432
"passed" es consistente con parametrización de pytest, no se investigó más a fondo — impacto
nulo en la conclusión: **suite 100% verde**).

**Conclusión FASE 0:** el working tree contiene una evolución real y sustancial (FASE 3 completa:
Parte A n8n/frontend + Parte B Python) que **no está en el último commit**, tal como advertía el
prompt de auditoría. No se trata de cambios sospechosos: son consistentes entre sí, tienen tests
propios y están reflejados también en el workflow n8n en vivo (ver sección 6). No se corrigió
nada; no aplica (0 tests fallidos).

---

## 1. Arquitectura general

V2 es **cloud-first + code-first**: un motor Python 100% determinístico (Decimal, nunca float)
hace todo el trabajo contable; n8n (self-hosted en este Codespace) es **pura orquestación**
(triggers, Google Drive, aprobación humana, frontend estático); un HTML/JS plano sin build es
la única interfaz de usuario. Ningún LLM decide nada contable (ver `V2_CONTRACTS.md` CONTRACT-016).

```
n8n (orquestación, Drive, aprobación humana, frontend)
        │  Execute Command
        ▼
run_batch.py ──► pipeline_tiquipaya.py ──► motor_tiquipaya.py ──► sap_writer.py
                        │                        │
                        │                        └─ excel_io.py (lectura SOLO LECTURA)
                        │
                        ├─► correcciones_tiquipaya.py (FASE 3 Parte B)
                        └─► publicar_cierre.py (marcador PROCESADO_<SHA256>.json)

consolidador_mensual.py ──► control_asignaciones.py (CONTROL 1)
                        └──► control_cxc_cxp.py (CONTROL 3)
   (posteriores al V2 diario, leen SAP diarios/GLOBAL, nunca al motor diario)
```

## 2. Diagrama conceptual del flujo (extremo a extremo)

```
ENTRADAS (CIERRE .xlsm diario, MAESTRO mensual único [MACROS+ATC], PLANTILLA SAP)
    ↓
LECTURA               excel_io.leer_cierre / leer_macros_bnb / leer_atc_mensual   [SOLO LECTURA]
    ↓
NORMALIZACIÓN         excel_io.normalize_text/normalize_codigo/to_decimal/money_str
    ↓
CLASIFICACIÓN         motor_tiquipaya.cruzar_vouchers (MATCH_EXACTO/AUTOCORRECCION_0_O/
                       MULTIPLE/POSIBLE_TYPO/NO_ENCONTRADO)
    ↓
CRUCES                motor_tiquipaya.cruzar_atc(_preconciliado), validar_ci
    ↓
VALIDACIONES          motor_tiquipaya._validar_partidas (post-asiento), sap_writer._validar_precondiciones
    ↓
REGLAS CONTABLES       ALQUILERES excluidos (REGLA A), ATC 110201003 vs 110201008 (REGLA B),
                       USD/DOLARES partida DEBE única (BR-016), fallback fecha_valor (BR-015)
    ↓
GENERACIÓN ASIENTO     motor_tiquipaya.construir_asiento()  [ETAPA 5]
    ↓
SAP                    sap_writer.generar_y_validar_sap()  [ETAPA 6 — escribe y RELEE de disco]
    ↓
RESULTADOS             pipeline_tiquipaya._construir_resultado_json / RESULTADO_TIQ_DD-MM-YYYY.json
    ↓
REVISIÓN               n8n: rama REVISAR (Wait+Form hoy) + n8n_frontend/revision_correccion.html
                       (GET /datos — agrupa excepciones[] por cierre)
    ↓
CORRECCIÓN AUTORIZADA  correcciones_tiquipaya.py + aplicar_correccion.py + POST /corregir
                       (FASE 3 Parte B — reproceso a REPROCESOS/, nunca sobre el original)
    ↓
PUBLICACIÓN            n8n: CONFIRMAR aprobación (Wait+Form) → Drive SUBIR SAP/RESULTADO →
                       MOVER cierre → publicar_cierre.py → marcador; también vía
                       POST /publicar-listos (módulo independiente, lote con batch_token)
    ↓
CONTROLES              consolidador_mensual.py (SAP_GLOBAL mensual) → control_asignaciones.py
                       (CONTROL 1: duplicados de Asignación) → control_cxc_cxp.py
                       (CONTROL 3: CxC/CxP acumulado)
    ↓
MARCADORES/HISTÓRICO/AUDITORÍA
    PROCESADO_<SHA256>.json · HISTORICO_ASIGNACIONES.csv · HISTORICO_CXC_CXP.csv ·
    HISTORICO_CXC_CXP_PERIODOS.json · HISTORICO_CORRECCIONES.csv · CONTROL_PROCESAMIENTO.csv (legacy)
```

## 3. Módulos Python (11 en la raíz) — ver detalle fila por fila en `V2_NODES.csv`

| Módulo | Líneas | Rol |
|---|---|---|
| `excel_io.py` | 767 | Lectura SOLO LECTURA de CIERRE/MACROS/ATC |
| `motor_tiquipaya.py` | 1344 | ETAPAS 1-5: cruces, cuadre, asiento (núcleo contable) |
| `sap_writer.py` | 481 | ETAPA 6: genera y valida el SAP diario |
| `pipeline_tiquipaya.py` | 703 | ETAPA 7: orquestación, idempotencia, marcador, corrección+reproceso |
| `run_batch.py` | 516 | Runner canónico de batch (rango de fechas de un mismo mes) |
| `correcciones_tiquipaya.py` | 377 | FASE 3 Parte B: valida y aplica correcciones EN MEMORIA |
| `aplicar_correccion.py` | 311 | CLI de FASE 3 Parte B, invocado por n8n |
| `publicar_cierre.py` | 146 | CLI: construye el marcador `PROCESADO_<SHA256>.json` local |
| `consolidador_mensual.py` | 632 | SAP GLOBAL mensual (posterior, solo lectura de SAP diarios) |
| `control_asignaciones.py` | 1370 | CONTROL 1: duplicados de Asignación + corrección validada por humano |
| `control_cxc_cxp.py` | 1353 | CONTROL 3: seguimiento acumulado CxC/CxP + cierre manual |

Total código de producción: **7 992 líneas** en 11 archivos. Tests: **8 848 líneas** en 18
archivos (`tests/`), **432 tests, 100% verdes**.

## 4. n8n — workflow `TIQ · PROCESAR CIERRES PENDIENTES · POC`

- Workflow ID `LkS0RHu9KEbHCR4p`, **160 nodos** (143 funcionales + 17 Sticky Notes /
  `DOCUMENTACION_VISUAL`), **153 conexiones**.
- Fuente de esta sección: export completo (nodes+connections+parámetros) leído **directamente
  de la base SQLite de n8n en modo solo-lectura** (`sqlite3 -readonly ~/.n8n/database.sqlite`),
  ya que el servidor MCP de n8n estaba desconectado al momento de esta auditoría (ver nota de
  limitación en la sección 8). El contenido leído así es el **realmente vigente** (`versionId`
  actual de `workflow_entity`, no una copia en caché de esta sesión).
- **Verificado explícitamente:** ese contenido es funcionalmente idéntico (mismos nodos,
  mismos parámetros, mismas conexiones) a un export completo tomado minutos antes por otra vía;
  las únicas diferencias entre ambos son 6 Sticky Notes con retoques cosméticos manuales
  posteriores del usuario — cero diferencias funcionales.
- **Hallazgo de proceso (no de código):** `workflow_entity.activeVersionId` = `ebb043e7...`
  (guardado 2026-09-13 01:30:26) mientras que el `versionId` actual (última edición guardada) es
  `bded7b63...` (10:52:07) — 5 versiones más adelante. Ver `V2_RISKS.csv` RISK-008.
- Tipos de nodo presentes: `webhook` ×9, `formTrigger` ×1, `manualTrigger` ×1, `googleDrive`
  ×26, `executeCommand` ×15, `code` ×34, `if`/`switch` ×20, `splitInBatches` ×1, `merge` ×2,
  `set` ×9, `readWriteFile`/`extractFromFile` ×20, `respondToWebhook` ×8, `wait` ×2,
  `stickyNote` ×17.
- **Fases visuales del canvas** (reordenadas por esta misma sesión en la tarea anterior, sin
  tocar lógica — ver commits/versiones de n8n `ddd03445`/`59f14723` en `workflow_history`):
  FASE 0 Entrada → FASE 1 Materialización local → FASE 2 Motor+Clasificación → FASE 3 Revisión
  del auditor (incluye los webhooks del frontend) → FASE 4 Publicación → FASE 4B Publicación
  múltiple (módulo independiente).
- **Webhooks activos:** `GET /webhook/tiq-revision` (sirve el HTML), `GET .../datos`,
  `POST .../observacion`, `POST .../pendiente`, `POST .../corregir`, `POST .../publicar-listos`.
  Ninguno tiene autenticación (diferido a rollout futuro, HANDOFF §16.4).

## 5. Frontend

`n8n_frontend/revision_correccion.html` — SPA estática (HTML+CSS+JS embebido, sin build, sin
framework), servida por el propio n8n vía `cat` en un nodo Execute Command. Consume
exclusivamente los 4 endpoints de acción + el de datos, con rutas **relativas** (nunca al
dominio del Codespace) para portabilidad futura. Incluye un modo `?demo=1` totalmente aislado
del flujo real, útil para revisión visual sin backend.

## 6. Integración con Google Drive

Exclusivamente desde n8n (26 nodos `googleDrive`): búsqueda/descarga de CIERRE, MAESTRO,
PLANTILLA y marcadores; subida de SAP/RESULTADO/marcador; movimiento de cierres a
`03_PROCESADOS`. **Python nunca implementa la API de Drive** (confirmado por lectura completa
de los 11 módulos: ningún import de `google-api-python-client` ni equivalente).

## 7. Dependencias externas

- `openpyxl` (lectura/escritura Excel, único motor de I/O de archivos `.xlsm`/`.xlsx`).
- `pytest` (solo en `/workspaces/.venv-caja`, no en el Python global del Codespace).
- n8n `2.38.7` self-hosted (SQLite como backend, ver `~/.n8n/database.sqlite`).
- Ninguna dependencia de IA/LLM en el código Python (confirmado: no hay imports de SDKs de
  Anthropic/OpenAI en ningún módulo de producción).

## 8. Clasificación de responsabilidades (resumen)

| Capa | Responsabilidad | Nunca hace |
|---|---|---|
| `excel_io.py` | Leer Excel, normalizar tipos | Cruzar, cuadrar, escribir |
| `motor_tiquipaya.py` | Reglas contables determinísticas | Leer/escribir archivos, publicar |
| `sap_writer.py` | Generar y validar el `.xlsx` SAP | Decidir contabilidad |
| `pipeline_tiquipaya.py` | Orquestar, idempotencia, trazabilidad | Reinterpretar reglas, tocar Drive |
| `correcciones_tiquipaya.py` | Validar y aplicar correcciones EN MEMORIA | Decidir si una corrección es correcta (eso es del auditor) |
| `run_batch.py` | Recorrer rango de fechas, invocar pipeline | Tocar Drive, corregir blockers |
| `consolidador_mensual.py` / `control_*.py` | Controles posteriores, solo lectura del GLOBAL | Modificar el motor diario |
| n8n | Triggers, Drive, aprobación humana, servir el frontend | Decidir contabilidad |
| frontend HTML/JS | Pintar datos, armar payloads | Decidir si algo es válido (eso lo valida Python) |

## 9. Limitaciones de esta auditoría (declaradas explícitamente)

- El servidor MCP de n8n estuvo **desconectado** durante esta sesión (`ConnectionRefused`);
  se sustituyó por lectura directa y de solo lectura de `~/.n8n/database.sqlite`
  (`sqlite3 -readonly`), que es una fuente igual o más autoritativa (es la base de datos real
  de n8n, no una capa intermedia), pero implica que no se usaron las herramientas de validación
  estructurada del MCP (p. ej. `validate_workflow`).
- No se leyeron línea por línea `control_asignaciones.py` (1370 líneas) ni `control_cxc_cxp.py`
  (1353 líneas) ni `consolidador_mensual.py` (632 líneas): se corroboraron mediante extracción
  de firmas de función/constantes (`grep`) contra la descripción exhaustiva ya existente en
  `HANDOFF_CODE_V2.md` §§13-15, más los nombres y conteos exactos de sus respectivas suites de
  test. Se marcan `CONFIRMADO_POR_MULTIPLES_FUENTES` en los CSV, no `CONFIRMADO_POR_CODIGO`
  línea a línea.
- El detalle exacto de los parámetros de filtro de cada nodo `googleDrive` (REGLA G, búsqueda
  exacta) no se releyó uno por uno; la existencia de la regla se infiere de la estructura
  IF-después-de-cada-BUSCAR del canvas y del contexto explícito de la auditoría (incidente real
  documentado). Marcado `REQUIERE_VALIDACION_HUMANA` en `V2_BUSINESS_RULES.csv` (BR-008).
- No se ejecutó ningún cierre real ni se tocó ningún archivo de producción/Drive: 100% análisis
  estático sobre código, tests y configuración ya existentes, tal como exigía el encargo.

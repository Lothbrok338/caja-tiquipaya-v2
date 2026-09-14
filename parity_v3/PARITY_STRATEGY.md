# PARITY_STRATEGY.md — Estrategia de paridad V2 vs V3 (FASE 4)

## Principio rector

**V2 es el oráculo.** El tag `v2.0-final` (commit `7dbcf93f7588baaa34d1e2bdd2b56af2830b1f3e`,
rama `v2-final-snapshot`) y el snapshot `snapshots/v2-final/n8n_workflow_active.json`
son la referencia inmutable de comportamiento correcto. Si en cualquier fase
futura la implementación real de V3 no reproduce lo que V2 ya hace hoy, **se
corrige V3**, nunca los contratos de `auditoria_v2/V2_CONTRACTS.md` ni los
432 tests de `tests/`.

## Qué existe hoy y qué no

Este documento nació en FASE 4, cuando V3 aún no tenía ningún módulo
Python (solo un esqueleto n8n `NoOp`/`Set` + Sticky Notes) y este arnés
solo podía dejar preparado el contrato de comparación, con la parte V3 de
cada test marcada `pytest.skip`.

A la fecha de FASE 5 (Módulo 07 · AUDITORIA, el último), ese trabajo ya
está completo: V3 tiene los 7 módulos (`v3/ingesta.py`, `v3/materializacion.py`,
`v3/motor.py`, `v3/clasificacion.py`, `v3/revision.py`, `v3/publicacion.py`,
`v3/auditoria.py`) implementados como adaptadores delgados sobre el código
real de V2, cada uno cableado en su subworkflow n8n correspondiente
(patrón Execute-Command: n8n construye el payload e invoca Python, Python
es la única autoridad). Los 18 contratos ya tienen comparación V2-vs-V3
real y verde — ver la sección "Cobertura de los 18 CONTRACT-*" más abajo.

## Estructura de este directorio

```
parity_v3/
├── PARITY_STRATEGY.md       (este documento)
├── PARITY_SCENARIOS.csv     (18 escenarios PARITY-001..018, uno por CONTRACT-*)
├── regla_g_reference.py     (especificacion ejecutable de REGLA G — no existe
│                              en ningun otro lugar del repo como codigo Python)
└── test_parity_scenarios.py (arnes pytest: 18 tests, uno por escenario)
```

Se ejecuta de forma **totalmente independiente** de la suite de V2:

```bash
python -m pytest parity_v3/ -v      # arnes de paridad (18 tests)
python -m pytest tests/ -q          # suite V2 original, sin cambios (432 tests)
```

Nunca se mezclan en la misma carpeta ni en el mismo comando por diseño: así
un `pytest` corrido sobre `tests/` (como hacía la auditoría original) sigue
reportando exactamente 432, sin contaminarse con los tests de paridad.

## Cómo funciona cada test hoy

Cada uno de los 18 tests en `test_parity_scenarios.py`:

1. Construye un insumo sintético mínimo (dict en memoria, o un `.xlsm`/`.xlsx`
   sintético vía `tests/xlsx_fixtures.py`, reutilizado por importación —
   nunca copiado ni modificado).
2. Ejecuta código **real** de V2 sobre ese insumo (`motor_tiquipaya`,
   `pipeline_tiquipaya`, `sap_writer`, `correcciones_tiquipaya`,
   `control_asignaciones`, `control_cxc_cxp` — ninguno de estos módulos fue
   tocado en ninguna fase).
3. Afirma (`assert`) el contrato correspondiente contra ese resultado real.
   **Si esta afirmación fallara, sería un hallazgo sobre V2 mismo** (no
   debería ocurrir dado que V2 está congelado y probado; de ocurrir, se
   reporta como hallazgo crítico, nunca se ajusta el test para que pase).
4. Invoca la implementación REAL de V3 (`v3.*`) sobre el mismo insumo (o,
   cuando el contrato es sobre un módulo determinístico independiente del
   cierre diario — REGLA G, CONTROL 1, CONTROL 3 —, sobre el mismo
   escenario/incidente ya verificado contra V2 arriba) y afirma que
   coincide. Ninguna de estas comparaciones usa `pytest.skip`: los 18
   contratos tienen hoy una comparación real y verde.

## Cobertura de los 18 CONTRACT-*

Ver `PARITY_SCENARIOS.csv` para el detalle completo. Resumen:

| Estado | Cantidad | Contratos |
|---|---|---|
| Verificado hoy en ambos lados, V2 y V3 coinciden (comparación real y verde) | 18 | CONTRACT-001 a CONTRACT-018 (todos) |

**18/18 contratos tienen una comparación V2-vs-V3 real y verde. 0 skipped.**
Ningún PASS fue forzado: cada test que compara contra V3 invoca la
implementación real del módulo correspondiente sobre el mismo insumo (o el
mismo escenario real, cuando se trata de un incidente reproducido) ya
verificado contra V2 en ese mismo test.

Historial de graduación por módulo:
- **Diseño del arnés (FASE 4):** CONTRACT-010 (REGLA G) y CONTRACT-016
  (sin IA en el núcleo contable) — verificables desde el día 1 porque V3
  aún no tenía código Python (cumplimiento trivial pero verificado, no
  asumido).
- **Módulo 02 · MATERIALIZACION:** CONTRACT-005 (original inmutable) —
  `v3.materializacion.materializar_cierre()` solo copia (lectura del
  origen), nunca abre en escritura ni mueve/renombra.
- **Módulo 03 · MOTOR PYTHON:** CONTRACT-001/002/003/004/018 — `v3.motor`
  invoca `pipeline_tiquipaya.procesar_cierre_completo()` (el mismo motor
  de V2) sin reinterpretar ninguna regla.
- **Módulo 04 · CLASIFICACION:** CONTRACT-011 (procesar y publicar
  separados) — `v3.clasificacion.clasificar_cierre()` es función pura,
  sin I/O; reforzado end-to-end por el Módulo 06 (ver abajo).
- **Módulo 05 · REVISION/CORRECCION:** CONTRACT-006/007/012/013/014 — `v3.revision`
  invoca `correcciones_tiquipaya.py`/`pipeline_tiquipaya.procesar_cierre_con_correccion()`/
  `aplicar_correccion._rutas_reproceso()` de V2 sin reimplementarlos,
  incluida la reclasificación del reproceso vía el MISMO `v3.clasificacion`
  del Módulo 04 (no una segunda clasificación paralela).
- **Módulo 06 · PUBLICACION:** CONTRACT-008/009 — `v3.publicacion` invoca
  la MISMA `pipeline_tiquipaya.construir_marcador_procesado()`/
  `calcular_sha256()`/`nombre_marcador_procesado()` de V2; el marcador
  escrito en DEV coincide byte-a-byte con lo que esa función real
  produce, y la idempotencia SHA256 se verifica publicando 2 veces el
  mismo cierre (2da corrida = YA_PUBLICADO, cero duplicación). Refuerza
  CONTRACT-011 de punta a punta: `publicable=True` sigue sin significar
  "publicado" hasta la llamada explícita a `publicar_cierre_dev()`.
- **Módulo 07 · AUDITORIA (último):** CONTRACT-015 (CONTROL 1) y
  CONTRACT-017 (CONTROL 3) — `v3.auditoria.ejecutar_control1_correccion()`
  y `v3.auditoria.evaluar_control3_idempotencia()` son delegados delgados
  que llaman EXACTAMENTE a `control_asignaciones.aplicar_correcciones_global()`
  y `control_cxc_cxp._estado_idempotencia()`; no existe una segunda
  versión de ninguno de los dos controles. `v3.auditoria` además
  consolida, sin decidir nada, la trazabilidad completa de los módulos
  01-06 en `base_dir_dev/auditoria/` (CONTRACT-011/CONTRACT-016 también
  cubiertos ahí: auditoría nunca publica, nunca usa IA).

## Caso especial: CONTRACT-010 (REGLA G)

La auditoría ya había señalado (`auditoria_v2/V2_BUSINESS_RULES.csv` BR-008,
`V2_TEST_AUDIT.csv` T-021) que la búsqueda EXACTA en Drive vive únicamente en
nodos n8n del workflow V2, sin ningún test automatizado y sin que se hubiera
releído línea por línea el parámetro exacto de cada nodo `googleDrive`. Por
eso `regla_g_reference.py` no es "el código de V2 copiado": es la **primera
especificación ejecutable** de la regla, derivada del enunciado de la regla y
de los códigos de estado (`CIERRE_NO_LOCALIZADO_EN_00_ENTRADA`,
`CIERRE_AMBIGUO_EN_00_ENTRADA`) confirmados literalmente dentro de
`snapshots/v2-final/n8n_workflow_active.json`. Sirve como el contrato que
tanto una futura verificación directa de los nodos n8n de V2 como una futura
implementación V3 deben satisfacer para los mismos 3 casos (1/0/>1
coincidencias).

## Mantenimiento futuro (post-FASE 5)

Con los 18 contratos ya en verde y 0 skipped, la única regla que sigue
aplicando hacia adelante es la del principio rector: si un cambio futuro
en cualquier `v3/*.py` o en el wiring n8n hiciera que alguno de estos
tests fallara, **se corrige V3**, nunca se relaja la aserción del test ni
se ajustan los contratos de `auditoria_v2/V2_CONTRACTS.md`. Un `FAILED`
aquí es siempre una señal real de divergencia respecto al oráculo V2.

## FASE 0 de esta fase — estado de la suite V2 (re-ejecutada, sin tocar nada)

Ver el reporte de cierre de esta fase en el chat para el resultado exacto de
`python -m pytest tests/ -q` capturado en el momento de esta entrega.

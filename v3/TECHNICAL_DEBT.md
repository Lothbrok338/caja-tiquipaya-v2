# v3/TECHNICAL_DEBT.md — Deuda técnica conocida de V3 (en construcción)

Este documento registra deuda técnica introducida deliberadamente durante la
implementación progresiva de V3, con su plan de resolución explícito. Debe
revisarse (y cada ítem cerrarse o reconfirmarse) antes de considerar V3
"terminado" para cualquier módulo.

---

## DEBT-001 — REGLA G duplicada en Python y JavaScript (Módulo 01 · INGESTA)

**Dónde:** `v3/ingesta.py::buscar_cierre_exacto()` (Python) y el nodo
`APLICAR - Busqueda exacta (REGLA G)` (Code/JS) dentro del subworkflow
`TIQ V3 · 01 INGESTA · DEV` (`CanZtkmnm0ukAC8c`).

**Qué pasó:** al implementar el módulo 01 (FASE 5, primera etapa), la
lógica de REGLA G se escribió dos veces — una en Python (para que
`parity_v3`/`tests_v3` pudieran probarla con `pytest`) y otra en JavaScript
(porque un nodo Code de n8n no puede importar un módulo Python; se optó por
un puerto directo para que el subworkflow fuera autocontenido y no
dependiera de un `Execute Command` solo para esta decisión).

**Por qué es un problema:** dos implementaciones de la misma regla de
negocio pueden divergir con el tiempo si se edita una sin la otra. Hoy
están sincronizadas (verificado manualmente y comentado en ambos archivos),
pero no hay ningún mecanismo automático que lo garantice.

**Por qué NO se corrigió de inmediato:** corregirlo implica reestructurar
el módulo 01 (reemplazar los nodos Code por el mismo patrón
Execute-Command-invoca-Python que sí se usó desde el inicio en el módulo
02 · MATERIALIZACION — ver más abajo), y la instrucción explícita de esta
fase fue no tocar el módulo 01 al implementar el módulo 02.

**Plan de resolución (antes de dar V3 por terminado):**
1. Reestructurar `CanZtkmnm0ukAC8c` para que use el mismo patrón que
   `j88aiRsPF7g9kxhD` (módulo 02): un nodo Code que arme el payload JSON,
   un `Execute Command` que invoque `python3 -m v3.ingesta` (agregar CLI a
   `v3/ingesta.py`, análoga a la de `v3/materializacion.py`), y un
   `readWriteFile`/`extractFromFile` que lea el resultado.
2. Eliminar el nodo Code JS `APLICAR - Busqueda exacta (REGLA G)` una vez
   que el `Execute Command` lo reemplace funcionalmente.
3. Re-ejecutar `parity_v3::test_PARITY_010` sin cambios en las aserciones
   (debe seguir en verde: la fuente de verdad sigue siendo
   `v3.ingesta.buscar_cierre_exacto`, ahora también invocada por n8n en
   vez de reimplementada).
4. Marcar este ítem como CERRADO en este documento, con la fecha y el
   commit/versión de n8n correspondiente.

**Estado:** CERRADO (commit `144a007`, "feat: add master availability
precheck before processing"). El subworkflow `TIQ V3 · 01 INGESTA · DEV`
(`CanZtkmnm0ukAC8c`) ya no contiene el nodo Code JS `APLICAR - Busqueda
exacta (REGLA G)` — verificado tanto en `v3/ingesta.py` (ver comentario
"CLI — cierra DEBT-001" antes de `main()`) como en el snapshot congelado
`snapshots/v3-final/CanZtkmnm0ukAC8c_01_ingesta.json` (13 nodos: IF de
ruteo, lectura real de Google Drive de solo lectura, armado de payload,
`Execute Command` que invoca `python3 -m v3.ingesta`, lectura del
resultado). Python (`v3.ingesta.buscar_cierre_exacto`) es la única
autoridad de REGLA G; n8n solo arma el payload y lee la salida, igual que
el módulo 02 en adelante.

Nota pendiente (no bloqueante): `parity_v3/PARITY_SCENARIOS.csv`
(fila PARITY-010) todavía trae la nota antigua "El lado n8n (Code JS en
CanZtkmnm0ukAC8c) replica esta misma logica; su sincronizacion se
verifica manualmente" — quedó desactualizada por el mismo motivo que este
archivo y conviene corregirla en el mismo commit que actualice esta
sección, pero no cambia el veredicto: el test `test_PARITY_010_...` sigue
verificando exclusivamente `v3.ingesta.buscar_cierre_exacto`.

---

## Principio aplicado a partir de aquí (Módulo 02 en adelante)

Para evitar repetir DEBT-001, el módulo 02 · MATERIALIZACION (`v3/materializacion.py`)
se diseñó desde el inicio con el patrón "Python es la única autoridad, n8n
solo invoca": el subworkflow `TIQ V3 · 02 MATERIALIZACION · DEV`
(`j88aiRsPF7g9kxhD`) no reimplementa ninguna decisión en JavaScript — arma
el payload, invoca `python3 -m v3.materializacion` vía `Execute Command`, y
lee el JSON de salida. Cero lógica de negocio nueva en JS desde este
módulo en adelante.

# Diagnóstico — Caja Ayacucho con Power Automate + Python (Railway)

Fecha: 2026-10-21 · Rama: `claude/charming-pasteur-l1uxy1` · Base: `main` @ `8a5c6e8`
Línea base: 378 tests OK (`PYTHONPATH=. python3 -m unittest discover -s tests`).

## 0. Lo que el repositorio NO contiene (hallazgos que cambian el plan)

| Lo que dice el prompt | Evidencia en el repo | Consecuencia |
|---|---|---|
| Mecanismo ZIP de Power Automate ya usado con Claude Code/Codex | Ningún `.zip`, `manifest.json`, `definition.json` ni mención a Power Automate | No puedo saber qué formato usaron. Necesito un ZIP exportado (ver §5). |
| Motor ya alojado en Railway / endpoints n8n | Cero código de servidor, cero referencias a n8n/Railway/Flask/FastAPI; el motor es CLI + librería, diseñado para "Cowork + Drive" | La API REST no existe: hay que construirla (hecho en Fase 0, §3). Si el motor Railway vive en **otro repo**, hay que pasármelo. |
| Caja América | Cero referencias | No puedo comparar Tiquipaya vs América. |
| Caja Ayacucho | Cero referencias, ningún cierre de ejemplo | **No hay evidencia para ninguna regla de Ayacucho.** Sin cierres reales no se implementa nada contable. |
| "Publicación y rectificación" | `grep -i rectific` = 0 resultados. Publicación existe solo como contrato (marcador `PROCESADO_<SHA256>.json`, tras confirmación humana) | Flujo 05 (Rectificación) no tiene motor que reutilizar: es desarrollo nuevo. |

## 1. Qué código Python reutilizar

| Módulo | Entrada pública útil | Reutilización directa para Ayacucho |
|---|---|---|
| `pipeline_tiquipaya.py` | `procesar_cierre_completo(ruta_cierre, ruta_maestro, ruta_plantilla_sap, ruta_sap_salida, metadata_cabecera, version_codigo, hashes_procesados, registros_control)`; `calcular_sha256`; `construir_marcador_procesado` | **Sí, es el punto de entrada del endpoint de procesamiento.** Ya da idempotencia por SHA256, estado, blockers y `resultado_json` sin datos personales. |
| `motor_tiquipaya.py` / `excel_io.py` | `ejecutar_v2`, `construir_asiento` | Vía pipeline; no llamarlos desde la API. |
| `sap_writer.py` | `generar_y_validar_sap` | Vía pipeline (valida debe=haber releyendo el archivo guardado). |
| `run_batch.py` | `ejecutar_batch` | Útil para "múltiples cierres" (Flujo de lote). |
| `consolidador_mensual.py` | `ejecutar_consolidacion` | Flujo 06 (GLOBAL mensual). |
| `control_asignaciones.py`, `control_cxc_cxp.py` | `ejecutar_control` | Controles posteriores al GLOBAL; dependen de un histórico persistente (ver §4). |

### Bloqueo para Ayacucho: el motor tiene Tiquipaya cableado
Constantes fijas que habría que parametrizar **por caja** (sin alterar Tiquipaya):
- Cuentas: `110101001` (haber), `110103012` (voucher/ATC neto), `110201008` (comisión ATC), `110101010` (USD) — `motor_tiquipaya.py:782-798`. `sap_writer` además prohíbe `110201003`.
- Cabecera SAP: Sociedad `BO01`, Centro de Beneficio `10010101`, tipo `SA`, referencia `CAJA TIQUIPAYA` (`run_batch.py:112`), texto `INGRESOS <MES> CBBA`, asignación `TIQUIPAYA <MES>` (`motor_tiquipaya.py:807-813`).
- Hoja `ATC TIQUIPAYA` (`excel_io.py:568`, `run_batch.py:138`), universos `SFC101/SFC102`, nombres `SAP_TIQ_*`, `RESULTADO_TIQ_*`, `SAP_GLOBAL_TIQ_*` (regex en consolidador y ambos controles).
- Regla de banco: vouchers siempre BNB, MACROS solo `Tablas Dinamicas Profesional`.

**Recomendación (no ejecutada):** introducir un objeto `CajaConfig` con los valores de Tiquipaya como default, inyectado en el pipeline, con un test de regresión que pruebe salida **idéntica byte a byte** para Tiquipaya antes/después. No se toca nada hasta tener cierres reales de Ayacucho que digan qué valores difieren.

## 2. Arquitectura de flujos (evaluación de la separación propuesta)

Propuesta: **4 flujos, no 6.**
1. **`01 Procesar cierre`** = Ingesta + Procesamiento + Validación/Resultados. Separarlos añade 2 puntos de falla (handoff entre flujos, pérdida de correlation id) sin ganancia; la trazabilidad se logra con *scopes* (Ingesta / API / Interpretar) y un único `correlation_id`.
2. **`02 Publicar`** (separado, por la autorización humana): aprobación → copia del SAP → marcador `PROCESADO_<SHA256>.json`. Separado porque espera horas/días y debe ser reintentable sin reprocesar.
3. **`03 Rectificar`** — nuevo (no existe motor). Se define cuando haya reglas de Ayacucho.
4. **`04 Consolidar mensual`** (+ controles 1 y 3 como pasos opcionales).

Flujo 00 (smoke, ya construido) valida HTTP Premium → Railway.

## 3. API (Fase 0 construida: `api_caja/`)
- `GET /v1/health` (sin auth) · `POST /v1/ping` (auth `X-API-Key`, eco de `X-Correlation-Id`, valida caja habilitada). 7 tests.
- Seguridad: claves en `API_KEYS` (varias, para rotación), comparación en tiempo constante, **falla cerrada (503) si no hay claves**.
- Fases siguientes (diseño):
  - `POST /v1/cajas/{caja}/cierres` → **202 + `Location`** (patrón asíncrono: la acción HTTP de Power Automate sigue `Location` sola, sin bucles "Until"); idempotencia por SHA256 del archivo + cabecera `Idempotency-Key`.
  - `GET /v1/jobs/{id}` (estado) · `GET /v1/jobs/{id}/resultado` (JSON del pipeline) · descarga del SAP.
  - Transporte de archivos: Power Automate envía el XLSM (multipart o base64; límite práctico ~100 MB por acción HTTP; **necesito el tamaño real de un cierre y del maestro**).
  - **API sin estado**: la fuente de verdad de marcadores PROCESADO e históricos queda en SharePoint (coherente con el contrato actual "Python nunca escribe en Drive"); Power Automate pasa `hashes_procesados` en cada llamada. Railway tiene disco efímero, así que evitar estado local salvo volumen/DB.

## 4. Conexiones requeridas
- Flujo 00: **ninguna** (la acción HTTP integrada es Premium pero no usa conexión).
- Flujo 01–04: SharePoint (y OneDrive solo si los cierres están ahí), Aprobaciones (Flujo 02), Outlook/Teams (notificación, opcional). Autenticación hacia Railway: ver decisión D2.

## 5. Qué necesito de ti (mínimo para avanzar)
1. **D1 — Formato de importación**: ¿*Importar paquete (heredado)* o *Importar solución*? Si no lo sabes: exporta cualquier flujo pequeño existente en ese formato y súbelo (sin credenciales; con eso comparo y corrijo mi estructura). Hoy entrego ambos formatos, **ninguno verificado contra tu tenant**.
2. **D2 — Secreto hacia Railway**: para el smoke, la API key se escribe al ejecutar. Para producción: (a) variable de entorno de solución tipo secreto (Azure Key Vault), o (b) HTTP con Microsoft Entra ID / API Management. Depende de las políticas de tu institución.
3. **D3 — ¿Dónde vive hoy el motor "en Railway"?** ¿Otro repo? ¿Hay endpoints n8n documentados?
4. **D4 — Cierres reales de Ayacucho (copias)** + el maestro/MACROS + la plantilla SAP, y de ser posible los de América para comparar. Sin esto no hay reglas de Ayacucho.
5. Nombre del sitio/biblioteca SharePoint donde residirán cierres, resultados, procesados.

## 6. Qué flujo primero
Flujo 00 (hecho) → desplegar API en Railway → **Flujo 01** en modo "dry run" sobre copias, sin escritura oficial. Antes del Flujo 01 hace falta `CajaConfig` (§1) y los cierres de Ayacucho (D4).

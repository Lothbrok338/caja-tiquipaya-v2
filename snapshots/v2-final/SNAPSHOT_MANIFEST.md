# SNAPSHOT_MANIFEST.md — v2-final (pre-congelado)

Snapshot de solo lectura. No se publicó, modificó ni tocó el workflow n8n en ningún momento
durante su generación: todo se obtuvo mediante consultas `sqlite3 -readonly` contra
`~/.n8n/database.sqlite`.

## Identificación

| Campo | Valor |
|---|---|
| Fecha/hora de generación (UTC) | 2026-09-13T19:48:56Z |
| Repositorio | `Lothbrok338/caja-tiquipaya-v2` |
| Branch actual | `main` |
| Git HEAD | `17afeea963439d01dd4285c83f8f3056d5d6a0be` |

## Workflow n8n

| Campo | Valor |
|---|---|
| Workflow ID | `LkS0RHu9KEbHCR4p` |
| Workflow name | `TIQ · PROCESAR CIERRES PENDIENTES · POC` |
| **activeVersionId** (congelado en este snapshot) | `ebb043e7-a5c1-48d7-a30a-cc3e02025949` |
| Etiqueta de esa versión en `workflow_history.name` | *"Fix critico: localizacion exacta en 00_ENTRADA_CIERRES (incidente real)"* |
| `versionId` actual del draft (más reciente, distinto del activo) | `bded7b63-112f-4d28-9e0e-cb3d0cb42136` (guardado 2026-09-13 10:52:07) |
| n8n version | `2.38.7` |
| Número de nodos (versión activa) | **147** (143 funcionales + 4 `stickyNote`/`DOCUMENTACION_VISUAL`) |
| Número de conexiones (versión activa) | **153** |

### Nota sobre `activeVersionId` vs draft actual

`workflow_entity.activeVersionId` = `ebb043e7...` mientras que `workflow_entity.versionId`
(última edición guardada) = `bded7b63...`, 5 versiones más adelante en `workflow_history`. Esto
significa que el draft más reciente **difiere** del activo: contiene, entre otras cosas, 8
Sticky Notes adicionales (13 vs 4 aquí) provenientes de ediciones posteriores no reactivadas —
incluida la reorganización puramente visual del canvas hecha en esta misma sesión — más 1 edición
manual del usuario posterior a esa reorganización. **Se siguió literalmente la instrucción de no
usar el draft si difiere del activo**: `n8n_workflow_active.json` se construyó exclusivamente a
partir de la fila de `workflow_history` cuyo `versionId = ebb043e7-a5c1-48d7-a30a-cc3e02025949`
(columnas `nodes`, `connections`, `nodeGroups` de esa fila específica — no de `workflow_entity`,
que refleja el draft actual). Este hallazgo ya estaba documentado como riesgo operativo
(`auditoria_v2/V2_RISKS.csv`, RISK-008); este snapshot lo resuelve para efectos de congelado
tomando explícitamente la versión ACTIVA, no la más reciente.

### Origen de cada sección del JSON

| Sección del JSON | Tabla/columna origen | Versionado por `ebb043e7`? |
|---|---|---|
| `nodes`, `connections`, `nodeGroups` | `workflow_history` (fila `versionId=ebb043e7...`) | Sí — exacto de esa versión |
| `name`, `id` | `workflow_entity.name` / `.id` (no cambian entre versiones) | N/A (constante) |
| `settings` | `workflow_entity.settings` (**valor actual**) | **No** — `workflow_history` no versiona `settings` en el esquema de esta instancia de n8n; se tomó el valor vigente hoy (`{"executionOrder":"v1","availableInMCP":true,"binaryMode":"separate"}`). No se detectó ningún indicio de que haya cambiado desde `ebb043e7` (ninguna operación de tipo `setWorkflowSettings` aparece en el historial de esta sesión ni en el `HANDOFF`), pero **queda declarado explícitamente como no verificado por versión** en vez de asumirlo. |
| `meta` | `workflow_entity.meta` (valor actual) | No versionado por fila (mismo criterio que `settings`) |
| `active` | Se fijó a `true` (el workflow está activo hoy: `workflow_entity.active=1`) | Metadato de estado, no de contenido |
| `pinData` | No existe columna `pinData` poblada en `workflow_history`; se dejó `{}` | N/A |

## Verificación de negocio

- ✅ **Corrección exacta del incidente 09/11 (REGLA G) presente**: se confirmó por búsqueda
  textual dentro de `n8n_workflow_active.json` que los códigos `CIERRE_NO_LOCALIZADO_EN_00_ENTRADA`
  y `CIERRE_AMBIGUO_EN_00_ENTRADA` existen literalmente, en los nodos `FASE3 - Buscar cierre en
  00_ENTRADA_CIERRES (publicar)`, `FASE3 - Anotar localizacion (publicar)` y
  `FASE3 - Pasar sin localizar (ya resuelto) (publicar)`. Esto es coherente con que la propia
  etiqueta de la versión (`workflow_history.name`) sea *"Fix critico: localizacion exacta en
  00_ENTRADA_CIERRES (incidente real)"* — la versión activa **es literalmente** el commit que
  introdujo esa corrección.
- ✅ **Conteo de nodos funcionales**: 143, coincide con el número de nodos funcionales
  reportado por la auditoría (`auditoria_v2/V2_NODES.csv`, filas con `node_type != DOCUMENTACION_VISUAL`
  entre las 160 filas n8n de esa auditoría corresponden al draft más reciente, 143 funcionales
  también — el conteo de nodos **funcionales** no cambió entre `ebb043e7` y el draft actual;
  solo cambió la cantidad de Sticky Notes, que nunca son lógica).
- ✅ **Conexiones**: 153, idéntico al número de conexiones auditado en `auditoria_v2/V2_SYSTEM_MAP.md`
  §4 y verificado aquí de forma independiente contando aristas de `connections` directamente
  desde esta fila histórica.

## Verificación de seguridad (sin secretos embebidos)

- Se recorrió recursivamente todo el JSON (`nodes`, `connections`, `settings`) buscando claves
  que contuvieran `accessToken`, `refreshToken`, `apiKey`, `secret`, `password`, `clientSecret`,
  `privateKey` o `token`.
- **3 coincidencias de la subcadena `"token"`**, las 3 explicadas y descartadas como falsos
  positivos: son los **nombres de nodo** `FASE3 - Calcular batch_token actual (publicar)`,
  `FASE3 - Validar batch_token (publicar)` e `IF - Batch token coincide (publicar)` — el
  `batch_token` es un **hash SHA256 de negocio** (control de concurrencia optimista sobre
  `resultado_batch.json`, ver `auditoria_v2/V2_BUSINESS_RULES.csv` BR-026), no una credencial.
- **30 nodos traen un bloque `credentials`**; los 30 usan exclusivamente el tipo
  `googleDriveOAuth2Api` y **todos** exponen únicamente `{"id": "aoEcEAFQQ38XcwZg", "name":
  "Google Drive account"}` — una referencia por id a la credencial almacenada (cifrada) en la
  tabla `credentials_entity` de n8n, nunca el secreto/token OAuth en sí. Confirmado: **cero
  claves inesperadas** dentro de ningún bloque `credentials` (se verificó que el conjunto de
  claves de cada uno es exactamente `{id, name}`).
- **Conclusión: sin secretos, tokens OAuth ni credenciales sensibles embebidas en el archivo.**

## Entorno

| Campo | Valor |
|---|---|
| Python (venv del proyecto, `/workspaces/.venv-caja`) | 3.14.2 |
| Resultado pytest | **432 passed**, 0 failed, 0 skipped (11.4s) |
| Número de tests | 432 (430 funciones `def test_...` detectadas; la diferencia es consistente con parametrización de pytest) |

## Integridad del archivo

| Campo | Valor |
|---|---|
| Archivo | `snapshots/v2-final/n8n_workflow_active.json` |
| Tamaño | 161 305 bytes |
| **SHA256** | `985ae1d8f7cc27082b4dcdb539d7f458142157e82e55b951cf15f79c6c06323c` |

## Cómo se generó (comandos ejecutados, todos de solo lectura)

```bash
sqlite3 -readonly ~/.n8n/database.sqlite \
  "SELECT nodes FROM workflow_history WHERE versionId='ebb043e7-a5c1-48d7-a30a-cc3e02025949';"
sqlite3 -readonly ~/.n8n/database.sqlite \
  "SELECT connections FROM workflow_history WHERE versionId='ebb043e7-a5c1-48d7-a30a-cc3e02025949';"
sqlite3 -readonly ~/.n8n/database.sqlite \
  "SELECT nodeGroups FROM workflow_history WHERE versionId='ebb043e7-a5c1-48d7-a30a-cc3e02025949';"
sqlite3 -readonly ~/.n8n/database.sqlite \
  "SELECT settings, meta FROM workflow_entity WHERE id='LkS0RHu9KEbHCR4p';"
```
Ensamblados con un script Python local (no persistido en el repo) en la forma de export estándar
de n8n (`name`, `nodes`, `connections`, `active`, `settings`, `id`, `versionId`, `nodeGroups`,
`meta`, `pinData`), para que el archivo sea reimportable tal cual en una instancia n8n si se
necesitara restaurar exactamente este estado.

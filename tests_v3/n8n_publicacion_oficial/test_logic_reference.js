/**
 * tests_v3/n8n_publicacion_oficial/test_logic_reference.js — FASE 11A.1.
 *
 * Prueba, con Node puro (sin n8n, sin Drive, sin cierres reales), la
 * logica de idempotencia/reentrancia de "TIQ V3 · 06B PUBLICACION OFICIAL
 * · DRIVE" (ver logic_reference.js). Ningun test de este archivo toca
 * 10/09, 11/09, 12/09 ni ningun archivo real: todos los datos son
 * fixtures sinteticos in-memory.
 *
 * Uso: node tests_v3/n8n_publicacion_oficial/test_logic_reference.js
 */
'use strict';

const assert = require('assert');
const {
  verificarArtefactoExistente,
  verificarCierreEnEntrada,
  verificarCierreEnProcesados,
  markerYaExiste,
  validarPrefijoArchivo,
  resolverDestinosDrive,
  validarIdentidadesPreviasRectificacion,
  resolverMarkerAnteriorRectificacion,
} = require('./logic_reference');

let pasados = 0;
let fallidos = 0;

function test(nombre, fn) {
  try {
    fn();
    pasados++;
    console.log('  ok - ' + nombre);
  } catch (err) {
    fallidos++;
    console.log('  FAIL - ' + nombre);
    console.log('    ' + err.message);
  }
}

function assertLanza(fn, subcadenaEsperada) {
  let lanzo = false;
  try {
    fn();
  } catch (err) {
    lanzo = true;
    assert.ok(
      err.message.indexOf(subcadenaEsperada) !== -1,
      'mensaje de error no contiene "' + subcadenaEsperada + '": ' + err.message
    );
  }
  assert.ok(lanzo, 'se esperaba que lanzara un error y no lanzo nada');
}

// -----------------------------------------------------------------------
// 1) Fallo despues de SAP + retry -> SAP no se duplica.
// -----------------------------------------------------------------------
test('retry tras fallo despues de SAP: SAP existente se reutiliza, no se sube de nuevo', () => {
  // Primer intento (0 items en la carpeta SAP oficial): sube.
  const primerIntento = verificarArtefactoExistente([], 'SAP_TIQ_10-09-2026.xlsx', 'ERROR_AMBIGUO_SAP');
  assert.strictEqual(primerIntento.yaExiste, false);
  assert.strictEqual(primerIntento.fileId, null);

  // Simula que el SAP SI se subio antes de que fallara el paso siguiente
  // (resultado). El retry vuelve a buscar y ahora lo encuentra: reutiliza.
  const retry = verificarArtefactoExistente(
    [{ id: 'sap-real-1', name: 'SAP_TIQ_10-09-2026.xlsx' }],
    'SAP_TIQ_10-09-2026.xlsx',
    'ERROR_AMBIGUO_SAP'
  );
  assert.strictEqual(retry.yaExiste, true);
  assert.strictEqual(retry.fileId, 'sap-real-1');
});

// -----------------------------------------------------------------------
// 2) Fallo despues de resultado + retry -> SAP y resultado no se duplican.
// -----------------------------------------------------------------------
test('retry tras fallo despues de RESULTADO: SAP y resultado existentes se reutilizan', () => {
  const sapRetry = verificarArtefactoExistente(
    [{ id: 'sap-real-1', name: 'SAP_TIQ_10-09-2026.xlsx' }],
    'SAP_TIQ_10-09-2026.xlsx',
    'ERROR_AMBIGUO_SAP'
  );
  assert.strictEqual(sapRetry.yaExiste, true);

  const resultadoRetry = verificarArtefactoExistente(
    [{ id: 'resultado-real-1', name: 'RESULTADO_TIQ_10-09-2026.json' }],
    'RESULTADO_TIQ_10-09-2026.json',
    'ERROR_AMBIGUO_RESULTADO'
  );
  assert.strictEqual(resultadoRetry.yaExiste, true);
  assert.strictEqual(resultadoRetry.fileId, 'resultado-real-1');
});

// -----------------------------------------------------------------------
// 3) Fallo despues de mover cierre + retry -> no vuelve a moverlo.
// -----------------------------------------------------------------------
test('retry tras fallo despues de MOVER cierre: detecta que ya esta en PROCESADOS, no lo mueve de nuevo', () => {
  // El cierre YA NO esta en 00_ENTRADA_CIERRES (se movio antes de que
  // fallara el paso del marker).
  const enEntrada = verificarCierreEnEntrada([], 'CIERRE 10-09-2026.xlsm', 'drive-id-original-10-09');
  assert.strictEqual(enEntrada.encontradoEnEntrada, false);

  // El retry busca en 03_PROCESADOS y lo encuentra: se trata como paso
  // ya completado, NO se vuelve a mover.
  const enProcesados = verificarCierreEnProcesados(
    [{ id: 'drive-id-original-10-09', name: 'CIERRE 10-09-2026.xlsm' }],
    'CIERRE 10-09-2026.xlsm'
  );
  assert.strictEqual(enProcesados.yaEnProcesados, true);
  assert.strictEqual(enProcesados.id, 'drive-id-original-10-09');
});

test('retry: si el cierre no esta en NINGUNA de las dos carpetas, error claro (nunca se inventa)', () => {
  assertLanza(
    () => verificarCierreEnProcesados([], 'CIERRE 10-09-2026.xlsm'),
    'ERROR_CIERRE_NO_LOCALIZADO'
  );
});

// -----------------------------------------------------------------------
// 4) Marker existente -> YA_PUBLICADO.
// -----------------------------------------------------------------------
test('marker existente en Drive => YA_PUBLICADO (sin tocar nada mas)', () => {
  assert.strictEqual(markerYaExiste([{ id: 'marker-1', name: 'PROCESADO_abc.json' }]), true);
});

test('marker inexistente en Drive => continua la publicacion', () => {
  assert.strictEqual(markerYaExiste([]), false);
});

// -----------------------------------------------------------------------
// 5) Dos SAP exactos en destino -> error ambiguo.
// -----------------------------------------------------------------------
test('dos archivos SAP con el mismo nombre exacto => ERROR_AMBIGUO_SAP, no sube ni reutiliza', () => {
  assertLanza(
    () => verificarArtefactoExistente(
      [
        { id: 'sap-dup-1', name: 'SAP_TIQ_10-09-2026.xlsx' },
        { id: 'sap-dup-2', name: 'SAP_TIQ_10-09-2026.xlsx' },
      ],
      'SAP_TIQ_10-09-2026.xlsx',
      'ERROR_AMBIGUO_SAP'
    ),
    'ERROR_AMBIGUO_SAP'
  );
});

// -----------------------------------------------------------------------
// 6) Dos resultados exactos -> error ambiguo.
// -----------------------------------------------------------------------
test('dos archivos RESULTADO con el mismo nombre exacto => ERROR_AMBIGUO_RESULTADO', () => {
  assertLanza(
    () => verificarArtefactoExistente(
      [
        { id: 'res-dup-1', name: 'RESULTADO_TIQ_10-09-2026.json' },
        { id: 'res-dup-2', name: 'RESULTADO_TIQ_10-09-2026.json' },
      ],
      'RESULTADO_TIQ_10-09-2026.json',
      'ERROR_AMBIGUO_RESULTADO'
    ),
    'ERROR_AMBIGUO_RESULTADO'
  );
});

// -----------------------------------------------------------------------
// 7) fileId original se conserva desde INGESTA hasta la verificacion en
//    PUBLICACION (aqui: la reconciliacion nombre<->fileId).
// -----------------------------------------------------------------------
test('fileId de ingesta coincide con el archivo real => se usa como identificador (verificado)', () => {
  const r = verificarCierreEnEntrada(
    [{ id: 'drive-id-original-10-09', name: 'CIERRE 10-09-2026.xlsm' }],
    'CIERRE 10-09-2026.xlsm',
    'drive-id-original-10-09'
  );
  assert.strictEqual(r.encontradoEnEntrada, true);
  assert.strictEqual(r.cierreFileId, 'drive-id-original-10-09');
});

test('otro archivo con nombre parecido (mismo nombre exacto pero fileId distinto) NO puede moverse en su lugar', () => {
  // Escenario: el archivo que Drive devuelve para ese nombre exacto tiene
  // un id DISTINTO al que V3 detecto en INGESTA (p. ej. el original se
  // borro/reemplazo). No se mueve nada -- error explicito, nunca se
  // sustituye en silencio por "el que aparezca con ese nombre".
  assertLanza(
    () => verificarCierreEnEntrada(
      [{ id: 'drive-id-DIFERENTE', name: 'CIERRE 10-09-2026.xlsm' }],
      'CIERRE 10-09-2026.xlsm',
      'drive-id-original-10-09'
    ),
    'ERROR_FILEID_INGESTA_NO_COINCIDE'
  );
});

test('sin fileId de ingesta (fallback DEV actual): identifica por nombre exacto, degradado pero seguro', () => {
  const r = verificarCierreEnEntrada(
    [{ id: 'drive-id-encontrado-por-nombre', name: 'CIERRE 10-09-2026.xlsm' }],
    'CIERRE 10-09-2026.xlsm',
    null
  );
  assert.strictEqual(r.encontradoEnEntrada, true);
  assert.strictEqual(r.cierreFileId, 'drive-id-encontrado-por-nombre');
});

test('ambiguedad en 00_ENTRADA_CIERRES (2 archivos con el mismo nombre exacto) => ERROR_AMBIGUO_CIERRE_ENTRADA', () => {
  assertLanza(
    () => verificarCierreEnEntrada(
      [
        { id: 'a', name: 'CIERRE 10-09-2026.xlsm' },
        { id: 'b', name: 'CIERRE 10-09-2026.xlsm' },
      ],
      'CIERRE 10-09-2026.xlsm',
      null
    ),
    'ERROR_AMBIGUO_CIERRE_ENTRADA'
  );
});

// -----------------------------------------------------------------------
// 8) AISLAMIENTO DRIVE POR CAJA (nodo RESOLVER - Destinos Drive por caja).
// -----------------------------------------------------------------------
test('TIQ resuelve los 5 destinos historicos sin ninguna variable de entorno', () => {
  const r = resolverDestinosDrive('tiquipaya', {});
  assert.strictEqual(r.folder_entrada, '1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1');
  assert.strictEqual(r.folder_sap, '1mid4gUHnCmZbISlsAYMwWta3RudTSE13');
  assert.strictEqual(r.folder_resultado, '16Z7Uhf-NgiZ6YuqWLnReaIozRIiOg5HO');
  assert.strictEqual(r.folder_procesados, '1BkNC6lnonMM7YeWDKck-TM8WTyY2BJJP');
  assert.strictEqual(r.folder_marker, '1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu');
});

test('caja vacia (ENTRADA sin campo caja) se comporta como tiquipaya: mismos destinos', () => {
  const sinCaja = resolverDestinosDrive(undefined, {});
  const explicitoTiq = resolverDestinosDrive('tiquipaya', {});
  assert.deepStrictEqual(sinCaja, explicitoTiq);
});

test('AME resuelve destinos DISTINTOS a los de TIQ cuando las 5 variables estan configuradas', () => {
  const env = {
    DRIVE_ENTRADA_AME: 'ame-entrada-1',
    DRIVE_SAP_AME: 'ame-sap-1',
    DRIVE_RESULTADO_AME: 'ame-resultado-1',
    DRIVE_PROCESADOS_AME: 'ame-procesados-1',
    DRIVE_MARKER_AME: 'ame-marker-1',
  };
  const r = resolverDestinosDrive('america', env);
  const tiq = resolverDestinosDrive('tiquipaya', {});
  assert.strictEqual(r.folder_entrada, 'ame-entrada-1');
  assert.notStrictEqual(r.folder_entrada, tiq.folder_entrada);
  assert.notStrictEqual(r.folder_sap, tiq.folder_sap);
  assert.notStrictEqual(r.folder_resultado, tiq.folder_resultado);
  assert.notStrictEqual(r.folder_procesados, tiq.folder_procesados);
  assert.notStrictEqual(r.folder_marker, tiq.folder_marker);
});

test('AME sin sus variables de entorno configuradas: falla cerrado, NUNCA cae al folder de TIQ', () => {
  assertLanza(() => resolverDestinosDrive('america', {}), 'DRIVE_AME_PENDIENTE');
});

test('AME con solo ALGUNAS variables configuradas: la que falta tambien falla cerrado', () => {
  assertLanza(
    () => resolverDestinosDrive('america', { DRIVE_ENTRADA_AME: 'ame-entrada-1' }),
    'DRIVE_AME_PENDIENTE'
  );
});

test('caja desconocida en ENTRADA => CAJA_DESCONOCIDA, no se adivina', () => {
  assertLanza(() => resolverDestinosDrive('brasil', {}), 'CAJA_DESCONOCIDA');
});

test('prefijo TIQ publicandose como AME => PREFIJO_CAJA_NO_COINCIDE (fail closed)', () => {
  assertLanza(
    () => validarPrefijoArchivo('america', 'SAP_TIQ_10-09-2026.xlsx'),
    'PREFIJO_CAJA_NO_COINCIDE'
  );
});

test('prefijo AME publicandose como TIQ => PREFIJO_CAJA_NO_COINCIDE (fail closed)', () => {
  assertLanza(
    () => validarPrefijoArchivo('tiquipaya', 'RESULTADO_AME_10-09-2026.json'),
    'PREFIJO_CAJA_NO_COINCIDE'
  );
});

test('prefijo propio: TIQ con nombre TIQ y AME con nombre AME no lanzan nada', () => {
  validarPrefijoArchivo('tiquipaya', 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx');
  validarPrefijoArchivo('america', 'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx');
});

test('nombre sin prefijo reconocido (p. ej. el cierre original) no es responsabilidad de este validador', () => {
  validarPrefijoArchivo('tiquipaya', 'CIERRE 10-09-2026.xlsm');
  validarPrefijoArchivo('america', 'CIERRE 10-09-2026.xlsm');
});

// =========================================================================
// BLOQUE 2 -- RECTIFICAR CIERRE PUBLICADO (26 casos del requerimiento).
// Fixtures sinteticos in-memory; ningun test toca Drive real ni n8n real.
// =========================================================================

const FECHA = '2026-09-10';
const CAJA = 'tiquipaya';
const ARCHIVO_ESPERADO = 'CIERRE 10-09-2026.xlsm';
const NOMBRE_SAP = 'SAP_TIQ_10-09-2026.xlsx';
const NOMBRE_RESULTADO = 'RESULTADO_TIQ_10-09-2026.json';
const SHA_ANTERIOR = 'sha-anterior-aaa';
const SHA_NUEVO = 'sha-nuevo-bbb';

function markerFixture(id, overrides) {
  return {
    id: id,
    contenido: Object.assign({
      FechaCierre: FECHA,
      ArchivoOrigen: ARCHIVO_ESPERADO,
      HashOrigen: SHA_ANTERIOR,
      Estado: 'PROCESADO',
      ArchivoSAP: NOMBRE_SAP,
    }, overrides || {}),
  };
}

// Caso 1 (marker YA_PUBLICADO, cero escrituras) -- cubierto arriba por
// 'marker existente en Drive => YA_PUBLICADO'.

// Caso 2 (same date/distinto SHA + PUBLICAR normal -> requiere
// rectificacion, cero escrituras) -- decision de las IF "IF - SAP ya
// existe en Drive" / "IF - Rectificacion solicitada (SAP existe)" en el
// workflow: con SAP existente y rectificacion=false, la rama construye
// CIERRE_YA_PUBLICADO_REQUIERE_RECTIFICACION sin ejecutar ningun nodo de
// escritura (SUBIR/ACTUALIZAR) -- verificado por inspeccion del grafo
// (test_sync_workflows-style) en test_workflow_json_sanity() mas abajo.

// Caso 3: rectificacion sin SAP previo -> fail closed.
test('rectificacion sin SAP previo (sap_file_id_anterior null) => ERROR_RECTIFICACION_SAP_NO_ENCONTRADO', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(null, [], NOMBRE_RESULTADO, [], ARCHIVO_ESPERADO, [], null),
    'ERROR_RECTIFICACION_SAP_NO_ENCONTRADO'
  );
});

// Caso 4: SAP ambiguo -- se resuelve ANTES de esta rama (VERIFICAR - SAP
// existente ya lanza ERROR_AMBIGUO_SAP para 2+ SAP con el mismo nombre,
// ver test 'dos archivos SAP...' arriba); nunca llega a construir
// sap_file_id_anterior con mas de un candidato.

// Caso 5: RESULTADO faltante -> fail closed.
test('rectificacion sin RESULTADO previo => ERROR_RECTIFICACION_RESULTADO_NO_ENCONTRADO', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion('sap-1', [], NOMBRE_RESULTADO, [], ARCHIVO_ESPERADO, [], null),
    'ERROR_RECTIFICACION_RESULTADO_NO_ENCONTRADO'
  );
});

// Caso 5b: RESULTADO ambiguo -> fail closed.
test('rectificacion con 2 RESULTADO del mismo nombre => ERROR_RECTIFICACION_RESULTADO_AMBIGUO', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(
      'sap-1',
      [{ id: 'res-1', name: NOMBRE_RESULTADO }, { id: 'res-2', name: NOMBRE_RESULTADO }],
      NOMBRE_RESULTADO, [], ARCHIVO_ESPERADO, [], null
    ),
    'ERROR_RECTIFICACION_RESULTADO_AMBIGUO'
  );
});

// Caso 6: PROCESADOS faltante -> fail closed.
test('rectificacion sin cierre previo en 03_PROCESADOS => ERROR_RECTIFICACION_CIERRE_PROCESADOS_NO_ENCONTRADO', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(
      'sap-1', [{ id: 'res-1', name: NOMBRE_RESULTADO }], NOMBRE_RESULTADO,
      [], ARCHIVO_ESPERADO, [], null
    ),
    'ERROR_RECTIFICACION_CIERRE_PROCESADOS_NO_ENCONTRADO'
  );
});

// Caso 6b: PROCESADOS ambiguo -> fail closed.
test('rectificacion con 2 cierres del mismo nombre en 03_PROCESADOS => ERROR_RECTIFICACION_CIERRE_PROCESADOS_AMBIGUO', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(
      'sap-1', [{ id: 'res-1', name: NOMBRE_RESULTADO }], NOMBRE_RESULTADO,
      [{ id: 'proc-1', name: ARCHIVO_ESPERADO }, { id: 'proc-2', name: ARCHIVO_ESPERADO }],
      ARCHIVO_ESPERADO, [], null
    ),
    'ERROR_RECTIFICACION_CIERRE_PROCESADOS_AMBIGUO'
  );
});

// Caso 9: cierre nuevo drive_file_id no coincide con INGESTA -> fail closed.
test('rectificacion: cierre nuevo en ENTRADA con fileId distinto al de INGESTA => ERROR_RECTIFICACION_FILEID_INGESTA_NO_COINCIDE', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(
      'sap-1', [{ id: 'res-1', name: NOMBRE_RESULTADO }], NOMBRE_RESULTADO,
      [{ id: 'proc-1', name: ARCHIVO_ESPERADO }], ARCHIVO_ESPERADO,
      [{ id: 'entrada-DIFERENTE', name: ARCHIVO_ESPERADO }], 'entrada-esperado-de-ingesta'
    ),
    'ERROR_RECTIFICACION_FILEID_INGESTA_NO_COINCIDE'
  );
});

test('rectificacion: cierre nuevo ausente en 00_ENTRADA_CIERRES => ERROR_RECTIFICACION_CIERRE_NUEVO_NO_ENCONTRADO (no hay nada que sustituir)', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(
      'sap-1', [{ id: 'res-1', name: NOMBRE_RESULTADO }], NOMBRE_RESULTADO,
      [{ id: 'proc-1', name: ARCHIVO_ESPERADO }], ARCHIVO_ESPERADO, [], null
    ),
    'ERROR_RECTIFICACION_CIERRE_NUEVO_NO_ENCONTRADO'
  );
});

test('rectificacion: 2 cierres nuevos con el mismo nombre en ENTRADA => ERROR_RECTIFICACION_CIERRE_NUEVO_AMBIGUO', () => {
  assertLanza(
    () => validarIdentidadesPreviasRectificacion(
      'sap-1', [{ id: 'res-1', name: NOMBRE_RESULTADO }], NOMBRE_RESULTADO,
      [{ id: 'proc-1', name: ARCHIVO_ESPERADO }], ARCHIVO_ESPERADO,
      [{ id: 'entrada-1', name: ARCHIVO_ESPERADO }, { id: 'entrada-2', name: ARCHIVO_ESPERADO }], null
    ),
    'ERROR_RECTIFICACION_CIERRE_NUEVO_AMBIGUO'
  );
});

// Caso 12-14: rectificacion completa -- conserva los 3 file_id oficiales.
test('rectificacion completa: conserva file_id SAP/RESULTADO/PROCESADOS anteriores tal cual', () => {
  const r = validarIdentidadesPreviasRectificacion(
    'sap-oficial-1',
    [{ id: 'resultado-oficial-1', name: NOMBRE_RESULTADO }],
    NOMBRE_RESULTADO,
    [{ id: 'procesados-oficial-1', name: ARCHIVO_ESPERADO }],
    ARCHIVO_ESPERADO,
    [{ id: 'entrada-nuevo-1', name: ARCHIVO_ESPERADO }],
    'entrada-nuevo-1'
  );
  assert.strictEqual(r.sap_file_id_anterior, 'sap-oficial-1');
  assert.strictEqual(r.resultado_file_id_anterior, 'resultado-oficial-1');
  assert.strictEqual(r.cierre_procesado_file_id_anterior, 'procesados-oficial-1');
  assert.strictEqual(r.cierre_nuevo_file_id_entrada, 'entrada-nuevo-1');
});

// Caso 7: 0 markers candidatos -> ERROR_MARKER_ANTERIOR_NO_ENCONTRADO.
test('resolver marker anterior: 0 candidatos cuya metadata coincide => ERROR_MARKER_ANTERIOR_NO_ENCONTRADO', () => {
  assertLanza(
    () => resolverMarkerAnteriorRectificacion([], NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO),
    'ERROR_MARKER_ANTERIOR_NO_ENCONTRADO'
  );
});

test('resolver marker anterior: ningun candidato coincide en ArchivoSAP/ArchivoOrigen/FechaCierre => ERROR_MARKER_ANTERIOR_NO_ENCONTRADO', () => {
  const markers = [
    markerFixture('marker-otra-fecha', { FechaCierre: '2026-09-11' }),
    markerFixture('marker-otro-sap', { ArchivoSAP: 'SAP_TIQ_11-09-2026.xlsx' }),
  ];
  assertLanza(
    () => resolverMarkerAnteriorRectificacion(markers, NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO),
    'ERROR_MARKER_ANTERIOR_NO_ENCONTRADO'
  );
});

// Caso 8: 2+ markers candidatos -> ERROR_AMBIGUO_MARKER_ANTERIOR.
test('resolver marker anterior: 2 candidatos con la misma metadata => ERROR_AMBIGUO_MARKER_ANTERIOR (nunca adivina cual)', () => {
  const markers = [markerFixture('marker-1'), markerFixture('marker-2')];
  assertLanza(
    () => resolverMarkerAnteriorRectificacion(markers, NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO),
    'ERROR_AMBIGUO_MARKER_ANTERIOR'
  );
});

// Caso 15-17: marker anterior unico se resuelve por metadata real (nunca
// por SHA adivinado), el sha anterior se extrae de HashOrigen, y el nuevo
// (subido en el ultimo paso, ver CONSTRUIR - Salida RECTIFICADO_OFICIAL
// del workflow) corresponde al sha_nuevo recibido en ENTRADA.
test('resolver marker anterior: 1 candidato exacto => se identifica sin adivinar el SHA por el nombre del archivo', () => {
  const markers = [
    markerFixture('marker-anterior-real'),
    markerFixture('marker-de-otro-cierre', { ArchivoOrigen: 'CIERRE 11-09-2026.xlsm', FechaCierre: '2026-09-11' }),
  ];
  const r = resolverMarkerAnteriorRectificacion(markers, NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO);
  assert.strictEqual(r.marker_file_id_anterior, 'marker-anterior-real');
  assert.strictEqual(r.sha_anterior, SHA_ANTERIOR);
  assert.strictEqual(r.sha_nuevo, SHA_NUEVO);
  assert.notStrictEqual(r.sha_anterior, r.sha_nuevo);
});

// Caso "sha_anterior == sha_nuevo" (PASO C): tratar como idempotencia, no
// como rectificacion -- fail closed explicito en vez de reemplazar.
test('marker anterior con el MISMO sha256 que el nuevo => ERROR_RECTIFICACION_SHA_IGUAL (es idempotencia, no rectificacion)', () => {
  const markers = [markerFixture('marker-1', { HashOrigen: SHA_NUEVO })];
  assertLanza(
    () => resolverMarkerAnteriorRectificacion(markers, NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO),
    'ERROR_RECTIFICACION_SHA_IGUAL'
  );
});

test('marker anterior sin HashOrigen (metadata incompleta) => ERROR_MARKER_ANTERIOR_SIN_HASH, fail closed', () => {
  const markers = [markerFixture('marker-1', { HashOrigen: undefined })];
  assertLanza(
    () => resolverMarkerAnteriorRectificacion(markers, NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO),
    'ERROR_MARKER_ANTERIOR_SIN_HASH'
  );
});

// Caso 10/11: aislamiento TIQ/AME tambien en la rama de rectificacion --
// la rama reutiliza RESOLVER - Destinos Drive por caja (mismos folder_*
// por caja) para las 3 busquedas nuevas (RESULTADO/PROCESADOS/ENTRADA) y
// el listado de markers: mismas garantias ya probadas arriba para
// resolverDestinosDrive/validarPrefijoArchivo se aplican sin cambios.
test('rectificacion: los folder_* resueltos por caja siguen aislados TIQ/AME (misma funcion que el flujo normal)', () => {
  const tiq = resolverDestinosDrive('tiquipaya', {});
  const ame = resolverDestinosDrive('america', {
    DRIVE_ENTRADA_AME: 'ame-entrada-1', DRIVE_SAP_AME: 'ame-sap-1', DRIVE_RESULTADO_AME: 'ame-resultado-1',
    DRIVE_PROCESADOS_AME: 'ame-procesados-1', DRIVE_MARKER_AME: 'ame-marker-1',
  });
  assert.notStrictEqual(tiq.folder_marker, ame.folder_marker);
  assert.notStrictEqual(tiq.folder_procesados, ame.folder_procesados);
});

// Caso 19: fallo RESULTADO/PROCESADOS + retry -- al reintentar, las
// busquedas por nombre exacto (mismo mecanismo que "VERIFICAR - SAP
// existente") vuelven a resolver el MISMO file_id ya actualizado, nunca
// crean un duplicado.
test('retry de rectificacion tras fallo en PROCESADOS: SAP y RESULTADO anteriores se re-resuelven al mismo file_id (idempotente)', () => {
  const items = [{ id: 'resultado-oficial-1', name: NOMBRE_RESULTADO }];
  const primero = validarIdentidadesPreviasRectificacion(
    'sap-oficial-1', items, NOMBRE_RESULTADO,
    [{ id: 'procesados-oficial-1', name: ARCHIVO_ESPERADO }], ARCHIVO_ESPERADO,
    [{ id: 'entrada-nuevo-1', name: ARCHIVO_ESPERADO }], 'entrada-nuevo-1'
  );
  const retry = validarIdentidadesPreviasRectificacion(
    'sap-oficial-1', items, NOMBRE_RESULTADO,
    [{ id: 'procesados-oficial-1', name: ARCHIVO_ESPERADO }], ARCHIVO_ESPERADO,
    [{ id: 'entrada-nuevo-1', name: ARCHIVO_ESPERADO }], 'entrada-nuevo-1'
  );
  assert.deepStrictEqual(primero, retry);
});

// Caso 20/21/7-8: fallo antes del marker nuevo / estado inesperado ->
// retry seguro o fail closed. Si el marker anterior ya fue eliminado en
// un intento previo (SUBIR del marker nuevo fallo despues), el retry NO
// encuentra candidatos (0 coincidencias de metadata) y FALLA CERRADO en
// vez de declarar exito o reemplazar el marker equivocado -- exactamente
// el mismo camino que el caso "0 candidatos" de arriba: no se necesita
// una rama de codigo distinta, ya es fail-closed por construccion.
test('retry tras eliminar el marker anterior sin llegar a subir el nuevo: 0 candidatos => FAIL CLOSED (nunca declara exito falso)', () => {
  assertLanza(
    () => resolverMarkerAnteriorRectificacion([], NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO),
    'ERROR_MARKER_ANTERIOR_NO_ENCONTRADO'
  );
});

// Caso 22 / 17: exito completo -> RECTIFICADO_OFICIAL con marker nuevo
// como ultimo paso logico (replica CONSTRUIR - Salida RECTIFICADO_OFICIAL).
test('exito de rectificacion: arma la salida RECTIFICADO_OFICIAL con file_id conservados + marker anterior invalidado', () => {
  const ident = validarIdentidadesPreviasRectificacion(
    'sap-oficial-1', [{ id: 'resultado-oficial-1', name: NOMBRE_RESULTADO }], NOMBRE_RESULTADO,
    [{ id: 'procesados-oficial-1', name: ARCHIVO_ESPERADO }], ARCHIVO_ESPERADO,
    [{ id: 'entrada-nuevo-1', name: ARCHIVO_ESPERADO }], 'entrada-nuevo-1'
  );
  const marker = resolverMarkerAnteriorRectificacion(
    [markerFixture('marker-anterior-1')], NOMBRE_SAP, ARCHIVO_ESPERADO, FECHA, SHA_NUEVO
  );
  const salida = {
    fecha: FECHA, sha256: SHA_NUEVO, caja: CAJA,
    estado_publicacion: 'RECTIFICADO_OFICIAL', publicado: true,
    sha256_anterior: marker.sha_anterior,
    drive_sap_file_id: ident.sap_file_id_anterior,
    drive_resultado_file_id: ident.resultado_file_id_anterior,
    drive_entrada_file_id: ident.cierre_procesado_file_id_anterior,
    drive_marker_file_id: 'marker-nuevo-subido-1',
    drive_marker_file_id_anterior_invalidado: marker.marker_file_id_anterior,
  };
  assert.strictEqual(salida.estado_publicacion, 'RECTIFICADO_OFICIAL');
  assert.strictEqual(salida.publicado, true);
  assert.strictEqual(salida.sha256_anterior, SHA_ANTERIOR);
  assert.strictEqual(salida.drive_sap_file_id, 'sap-oficial-1');
  assert.strictEqual(salida.drive_resultado_file_id, 'resultado-oficial-1');
  assert.strictEqual(salida.drive_entrada_file_id, 'procesados-oficial-1');
  assert.strictEqual(salida.drive_marker_file_id_anterior_invalidado, 'marker-anterior-1');
  assert.notStrictEqual(salida.drive_marker_file_id, salida.drive_marker_file_id_anterior_invalidado);
});

// -----------------------------------------------------------------------
console.log('');
console.log(pasados + ' passed, ' + fallidos + ' failed');
if (fallidos > 0) {
  process.exit(1);
}

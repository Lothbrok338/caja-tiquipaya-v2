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

// -----------------------------------------------------------------------
console.log('');
console.log(pasados + ' passed, ' + fallidos + ' failed');
if (fallidos > 0) {
  process.exit(1);
}

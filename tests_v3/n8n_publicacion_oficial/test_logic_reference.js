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
console.log('');
console.log(pasados + ' passed, ' + fallidos + ' failed');
if (fallidos > 0) {
  process.exit(1);
}

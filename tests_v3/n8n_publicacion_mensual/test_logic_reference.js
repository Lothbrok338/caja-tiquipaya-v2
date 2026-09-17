/**
 * tests_v3/n8n_publicacion_mensual/test_logic_reference.js — FASE 12D.
 * Prueba la logica de idempotencia de los subworkflows 07C/07D/07E con
 * Node puro (sin n8n, sin Drive), igual que test_logic_reference.js de
 * FASE 11A.1 hace para 06B.
 */
'use strict';

const assert = require('assert');
const {
  decidirDescarga,
  decidirCarpeta,
  decidirPublicacion,
} = require('./logic_reference.js');

let pass = 0;
let fail = 0;

function test(nombre, fn) {
  try {
    fn();
    pass += 1;
    console.log('PASS - ' + nombre);
  } catch (err) {
    fail += 1;
    console.log('FAIL - ' + nombre);
    console.log('       ' + err.message);
  }
}

// ---------------------------------------------------------------------
// 07C — descargar si existe
// ---------------------------------------------------------------------
test('07C: 0 coincidencias -> no hay nada que descargar', function () {
  const r = decidirDescarga([], 'HISTORICO_ASIGNACIONES.csv');
  assert.strictEqual(r.encontrado, false);
  assert.strictEqual(r.fileId, null);
});

test('07C: 1 coincidencia exacta -> se descarga ese fileId', function () {
  const r = decidirDescarga([{ name: 'HISTORICO_ASIGNACIONES.csv', id: 'F1' }], 'HISTORICO_ASIGNACIONES.csv');
  assert.strictEqual(r.encontrado, true);
  assert.strictEqual(r.fileId, 'F1');
});

test('07C: coincidencia parcial de nombre no cuenta', function () {
  const r = decidirDescarga([{ name: 'HISTORICO_ASIGNACIONES_VIEJO.csv', id: 'F1' }], 'HISTORICO_ASIGNACIONES.csv');
  assert.strictEqual(r.encontrado, false);
});

test('07C: >1 coincidencias -> ERROR_AMBIGUO_DESCARGA, no elige ninguna', function () {
  assert.throws(function () {
    decidirDescarga([{ name: 'X.csv', id: 'F1' }, { name: 'X.csv', id: 'F2' }], 'X.csv');
  }, /ERROR_AMBIGUO_DESCARGA/);
});

// ---------------------------------------------------------------------
// 07E — buscar o crear carpeta
// ---------------------------------------------------------------------
test('07E: 0 coincidencias -> crear carpeta nueva', function () {
  const r = decidirCarpeta([], 'GLOBAL');
  assert.strictEqual(r.existe, false);
});

test('07E: 1 coincidencia -> reutilizar la carpeta existente (no duplicar)', function () {
  const r = decidirCarpeta([{ name: 'GLOBAL', id: 'C1' }], 'GLOBAL');
  assert.strictEqual(r.existe, true);
  assert.strictEqual(r.carpetaId, 'C1');
});

test('07E: >1 coincidencias -> ERROR_AMBIGUO_CARPETA, no crea ni usa ninguna', function () {
  assert.throws(function () {
    decidirCarpeta([{ name: 'GLOBAL', id: 'C1' }, { name: 'GLOBAL', id: 'C2' }], 'GLOBAL');
  }, /ERROR_AMBIGUO_CARPETA/);
});

// ---------------------------------------------------------------------
// 07D — publicar (crear o actualizar)
// ---------------------------------------------------------------------
test('07D: 0 coincidencias -> crear (independiente de modo_si_existe)', function () {
  const r = decidirPublicacion([], 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', 'mantener');
  assert.strictEqual(r.accion, 'crear');
});

test('07D: 1 coincidencia + modo_si_existe=actualizar -> actualizar contenido', function () {
  const r = decidirPublicacion(
    [{ name: 'HISTORICO_ASIGNACIONES.csv', id: 'F1' }], 'HISTORICO_ASIGNACIONES.csv', 'actualizar'
  );
  assert.strictEqual(r.accion, 'actualizar');
  assert.strictEqual(r.fileId, 'F1');
});

test('07D: 1 coincidencia + modo_si_existe=mantener -> reutilizar sin tocar (GLOBAL inmutable)', function () {
  const r = decidirPublicacion(
    [{ name: 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', id: 'F1' }],
    'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', 'mantener'
  );
  assert.strictEqual(r.accion, 'reutilizar');
  assert.strictEqual(r.fileId, 'F1');
});

test('07D: >1 coincidencias -> ERROR_AMBIGUO_PUBLICACION sin crear ni actualizar nada', function () {
  assert.throws(function () {
    decidirPublicacion(
      [{ name: 'X.xlsx', id: 'F1' }, { name: 'X.xlsx', id: 'F2' }], 'X.xlsx', 'actualizar'
    );
  }, /ERROR_AMBIGUO_PUBLICACION/);
});

console.log('');
console.log('=========================================');
console.log(pass + ' passed, ' + fail + ' failed');
console.log('=========================================');

if (fail > 0) {
  process.exit(1);
}

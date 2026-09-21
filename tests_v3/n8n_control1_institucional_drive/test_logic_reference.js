/**
 * tests_v3/n8n_control1_institucional_drive/test_logic_reference.js
 *
 * Prueba, con Node puro (sin n8n, sin Drive), la decision de que publicar
 * a Drive tras un cierre de CONTROL 1 institucional (ver logic_reference.js
 * de este mismo directorio) -- en particular, que un reintento tras una
 * publicacion parcial (GLOBAL TIQ subido, GLOBAL AME no) complete lo
 * pendiente sin volver a fallar, y que el historico maestro nunca se
 * marque para publicar antes de que el par TIQ/AME este completo.
 *
 * Uso: node tests_v3/n8n_control1_institucional_drive/test_logic_reference.js
 */
'use strict';

const assert = require('assert');
const { decidirPublicacionControl1 } = require('./logic_reference');

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

const NOMBRE_DETALLE = 'CONTROL_ASIGNACIONES_INSTITUCIONAL_2026-09.json';
const BODY_BASE = { modo: 'official', confirmacion_cierre: true };

test('1. cierre fresco con ambas correcciones pendientes -> publica TIQ, AME e historico', () => {
  const r = { modo: 'cierre', estado: 'OK_SIN_DUPLICADOS', historico_actualizado: true, ruta_detalle_json: '/x/' + NOMBRE_DETALLE };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  const d = decidirPublicacionControl1(r, body, NOMBRE_DETALLE);
  assert.strictEqual(d.publicar_global_tiq, true);
  assert.strictEqual(d.publicar_global_ame, true);
  assert.strictEqual(d.hay_historico, true);
  assert.strictEqual(d.debe_publicar, true);
});

test('2. reintento tras TIQ ya publicado en Drive (par ya cerrado localmente) -> vuelve a incluir TIQ y completa AME', () => {
  // El par local ya esta cerrado desde el intento anterior: ejecutar_control1_institucional
  // devuelve YA_PROCESADO_SIN_CAMBIOS (sin historico_actualizado en ESTA corrida), pero el
  // reintento sigue enviando el MISMO body (mismas correcciones) porque el cliente no sabe
  // que Drive quedo a medias.
  const r = { modo: 'cierre', estado: 'YA_PROCESADO_SIN_CAMBIOS' };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  const d = decidirPublicacionControl1(r, body, NOMBRE_DETALLE);
  assert.strictEqual(d.publicar_global_tiq, true, 'TIQ debe reintentarse (subida en modo actualizar es un no-op inofensivo)');
  assert.strictEqual(d.publicar_global_ame, true, 'AME (el que realmente fallo en Drive) debe completarse');
  assert.strictEqual(d.hay_historico, true, 'el historico maestro, nunca subido en el intento anterior, debe publicarse ahora');
});

test('3. simetrico: reintento con AME ya publicado y TIQ pendiente en Drive -> misma decision (TIQ y AME ambos se re-incluyen)', () => {
  const r = { modo: 'cierre', estado: 'YA_PROCESADO_SIN_CAMBIOS' };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  const d = decidirPublicacionControl1(r, body, NOMBRE_DETALLE);
  assert.strictEqual(d.publicar_global_tiq, true);
  assert.strictEqual(d.publicar_global_ame, true);
});

test('4. ambos ya publicados y cerrados, reintento sin cambios -> idempotente (vuelve a incluir, no falla)', () => {
  const r = { modo: 'cierre', estado: 'YA_PROCESADO_SIN_CAMBIOS' };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  const d = decidirPublicacionControl1(r, body, NOMBRE_DETALLE);
  assert.strictEqual(d.debe_publicar, true);
  assert.strictEqual(d.publicar_global_tiq, true);
  assert.strictEqual(d.publicar_global_ame, true);
});

test('5. estado inesperado (par distinto del ya cerrado) -> fail closed: nada se publica', () => {
  const r = { modo: 'cierre', estado: 'GLOBAL_MODIFICADO_REQUIERE_REVISION' };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  const d = decidirPublicacionControl1(r, body, NOMBRE_DETALLE);
  assert.deepStrictEqual(d, { debe_publicar: false, hay_detalle: false, hay_historico: false, publicar_global_tiq: false, publicar_global_ame: false });
});

test('5b. ERROR_TECNICO -> fail closed: nada se publica', () => {
  const r = { estado: 'ERROR_TECNICO' };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  const d = decidirPublicacionControl1(r, body, NOMBRE_DETALLE);
  assert.strictEqual(d.debe_publicar, false);
});

test('6. historico maestro nunca se publica antes de que el cierre este completo (PRELIMINAR / pendientes)', () => {
  const r1 = { modo: 'preliminar', estado: 'REVISAR_DUPLICADOS_ENCONTRADOS' };
  const body = Object.assign({}, BODY_BASE, { correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] });
  assert.strictEqual(decidirPublicacionControl1(r1, body, NOMBRE_DETALLE).hay_historico, false);

  const r2 = { modo: 'cierre', estado: 'REVISAR_DUPLICADOS_ENCONTRADOS', historico_actualizado: false };
  assert.strictEqual(decidirPublicacionControl1(r2, body, NOMBRE_DETALLE).hay_historico, false, 'cierre bloqueado por pendientes no debe publicar historico');

  const r3 = { modo: 'cierre', estado: 'OK_SIN_DUPLICADOS', historico_actualizado: true };
  assert.strictEqual(decidirPublicacionControl1(r3, body, NOMBRE_DETALLE).hay_historico, true, 'solo al completar el cierre se publica el historico');
});

test('modo dev/preliminar nunca publica nada', () => {
  const r = { modo: 'cierre', estado: 'OK_SIN_DUPLICADOS', historico_actualizado: true };
  const body = { modo: 'dev', correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[16, 'C', 'D']] };
  assert.deepStrictEqual(decidirPublicacionControl1(r, body, NOMBRE_DETALLE), { debe_publicar: false, hay_detalle: false, hay_historico: false, publicar_global_tiq: false, publicar_global_ame: false });
});

console.log('');
console.log(pasados + ' pasados, ' + fallidos + ' fallidos');
if (fallidos > 0) {
  process.exit(1);
}

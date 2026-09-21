/**
 * tests_v3/n8n_control3_fuente_drive/test_nodos.js -- FASE 12F (institucional).
 *
 * Ejecuta, con Node puro (sin n8n ni Drive), el codigo REAL de los nodos Code que
 * materializan las entradas de CONTROL 3 INSTITUCIONAL desde Drive (AMBOS GLOBAL,
 * TIQ y AME, del mismo periodo, nunca por caja) y verifica que ese mismo texto es
 * el desplegado en el snapshot de BACKEND DEV.
 *
 * Uso: node tests_v3/n8n_control3_fuente_drive/test_nodos.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const dirNodos = path.join(__dirname, 'nodos');
const snapshot = path.join(__dirname, '..', '..', 'snapshots', 'v3-final', 'aLs1f3GMqswbaENA_backend_dev.json');
const cargar = function (n) { return fs.readFileSync(path.join(dirNodos, n + '.js'), 'utf8'); };

function ejecutar(codigo, nodos, entradas, json, env) {
  const $ = function (nombre) {
    if (!(nombre in nodos)) throw new Error('nodo no mockeado: ' + nombre);
    const items = nodos[nombre];
    return { first: function () { return items[0]; }, all: function () { return items; } };
  };
  const $input = { all: function () { return entradas || []; }, first: function () { return (entradas || [])[0]; } };
  return new Function('$', '$input', '$json', '$execution', '$env', 'Buffer', codigo)($, $input, json || {}, { id: 'test-1' }, env || {}, Buffer);
}
let pasados = 0, fallidos = 0;
function test(nombre, fn) {
  try { fn(); pasados++; console.log('PASS - ' + nombre); }
  catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); }
}

const WH = function (body) { return { 'WEBHOOK control3': [{ json: { body: body } }] }; };
const RC = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9 }))[0].json;
const G_TIQ = 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', G_AME = 'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx';
const H = 'HISTORICO_CXC_CXP.csv', P = 'HISTORICO_CXC_CXP_PERIODOS.json';
const NODOS_C = function (gTiq, gAme, h, p) {
  const mk = function (pref, arr) { return arr.map(function (n, i) { return { json: n === null ? {} : { id: pref + i, name: n } }; }); };
  return {
    'RESOLVER control3 (periodo y carpetas)': [{ json: RC }],
    'BUSCAR GLOBAL oficial CONTROL3 (Drive)': mk('gt', gTiq),
    'BUSCAR GLOBAL AME oficial CONTROL3 (Drive)': mk('ga', gAme),
    'BUSCAR historico CxC/CxP maestro (Drive)': mk('h', h),
    'BUSCAR periodos CxC/CxP maestro (Drive)': mk('p', p),
  };
};
const clasificar = function (gTiq, gAme, h, p) { return ejecutar(cargar('clasificar'), NODOS_C(gTiq, gAme, h, p), []).map(function (i) { return i.json; }); };

test('resolver: septiembre 2026 -> nombres TIQ+AME, dir aislado control3_institucional_entrada/2026-09', function () {
  assert.strictEqual(RC.periodo, '2026-09');
  assert.strictEqual(RC.nombre_global_tiq, G_TIQ);
  assert.strictEqual(RC.nombre_global_ame, G_AME);
  assert.strictEqual(RC.nombre_historico, H);
  assert.strictEqual(RC.nombre_periodos, P);
  assert.ok(RC.dir_entrada.endsWith('/dev_workdir/control3_institucional_entrada/2026-09'));
  assert.ok(!/\/global\/|publicacion|\/america\//.test(RC.dir_entrada));
  assert.strictEqual(RC.carpeta_global_id, '1KREzDpgptWRwuArA1qYco49rplOEeeNU');
  assert.strictEqual(RC.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.strictEqual(RC.carpeta_control3_id, '15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_');
});
test('resolver: nunca lee `caja` del body -- CONTROL 3 institucional no depende del selector', function () {
  assert.ok(!('caja' in RC));
  const conCaja = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, caja: 'america' }))[0].json;
  assert.strictEqual(conCaja.nombre_global_tiq, G_TIQ);
  assert.strictEqual(conCaja.nombre_global_ame, G_AME);
  assert.ok(!('caja' in conCaja));
});
test('resolver: anio/mes invalidos -> PERIODO_INVALIDO', function () {
  [{ anio: 2026, mes: 13 }, { anio: '2026', mes: 9 }, { anio: 1999, mes: 9 }, {}].forEach(function (b) {
    assert.throws(function () { ejecutar(cargar('resolver'), WH(b)); }, /PERIODO_INVALIDO/);
  });
});
test('clasificar: ambos GLOBAL + maestros institucionales de Drive -> 4 descargas en control3_institucional_entrada', function () {
  const r = clasificar([G_TIQ], [G_AME], [H], [P]);
  assert.deepStrictEqual(r.map(function (i) { return i.tipo; }), ['global_tiq', 'global_ame', 'historico', 'periodos']);
  r.forEach(function (i) { assert.strictEqual(i.ruta_destino, RC.dir_entrada + '/' + i.name); });
});
test('clasificar: primera ejecucion (sin maestros) -> solo ambos GLOBAL', function () {
  const r = clasificar([G_TIQ], [G_AME], [null], [null]);
  assert.deepStrictEqual(r.map(function (i) { return i.tipo; }), ['global_tiq', 'global_ame']);
  assert.strictEqual(r[0].maestros_en_drive, false);
});
test('clasificar: falta un GLOBAL -> GLOBAL_OFICIAL_NO_ENCONTRADO; duplicados -> ERROR_AMBIGUO_*', function () {
  assert.throws(function () { clasificar([null], [G_AME], [H], [P]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
  assert.throws(function () { clasificar([G_TIQ], [null], [H], [P]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
  assert.throws(function () { clasificar([G_TIQ, G_TIQ], [G_AME], [H], [P]); }, /ERROR_AMBIGUO_GLOBAL/);
  assert.throws(function () { clasificar([G_TIQ], [G_AME, G_AME], [H], [P]); }, /ERROR_AMBIGUO_GLOBAL/);
  assert.throws(function () { clasificar([G_TIQ], [G_AME], [H, H], [P]); }, /ERROR_AMBIGUO_HISTORICO/);
  assert.throws(function () { clasificar([G_TIQ], [G_AME], [H], [P, P]); }, /ERROR_AMBIGUO_PERIODOS/);
});
test('clasificar: historico sin libro de periodos (o al reves) -> MAESTROS_CXC_CXP_INCOMPLETOS', function () {
  assert.throws(function () { clasificar([G_TIQ], [G_AME], [H], [null]); }, /MAESTROS_CXC_CXP_INCOMPLETOS/);
  assert.throws(function () { clasificar([G_TIQ], [G_AME], [null], [P]); }, /MAESTROS_CXC_CXP_INCOMPLETOS/);
});
test('clasificar: ignora archivos con otro nombre (snapshots/otros periodos nunca son fuente)', function () {
  const r = clasificar([G_TIQ, 'SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx'], [G_AME], [H, 'HISTORICO_CXC_CXP_2026-08.csv'], [P]);
  assert.deepStrictEqual(r.map(function (i) { return i.name; }), [G_TIQ, G_AME, H, P]);
});
test('clasificar: nunca busca ni descarga un reporte previo del periodo (ejecutar_control3_institucional genera el suyo propio)', function () {
  const c = cargar('clasificar');
  assert.ok(!/BUSCAR reporte del periodo CONTROL3 \(Drive\)/.test(c));
});
test('restaurar: devuelve el item original del webhook', function () {
  const w = WH({ anio: 2026, mes: 9 });
  assert.deepStrictEqual(ejecutar(cargar('restaurar'), w, [{ json: { x: 1 } }])[0].json, w['WEBHOOK control3'][0].json);
});
test('construir_payload: nunca lee `caja` del body -- sin fallback a tiquipaya', function () {
  assert.ok(!/body\.caja|t\.caja|'caja'/.test(cargar('construir_payload')));
});
test('construir_payload: PRELIMINAR por defecto; CIERRE (sella el periodo) solo con confirmacion_cierre=true explicito', function () {
  const payload = function (body) {
    const p = ejecutar(cargar('construir_payload'), WH(Object.assign({ anio: 2026, mes: 9 }, body)))[0].json;
    return JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  };
  assert.deepStrictEqual([payload({}).confirmacion_cierre, payload({}).dry_run], [false, false]);
  assert.strictEqual(payload({ confirmacion_cierre: true }).confirmacion_cierre, true);
  assert.strictEqual(payload({ confirmacion_cierre: 'true' }).confirmacion_cierre, false);
  assert.ok(!/\.item\b/.test(cargar('construir_payload')));
});
test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8')); const nodos = (wf.workflow || wf).nodes;
  const mapa = { 'RESOLVER control3 (periodo y carpetas)': 'resolver', 'CLASIFICAR - Artefactos de CONTROL 3 en Drive': 'clasificar',
    'RESTAURAR - Item del webhook control3': 'restaurar', 'CONSTRUIR payload control3': 'construir_payload' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    assert.ok(nodo, 'falta nodo ' + nombre);
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), 'desalineado: ' + nombre);
  });
});
test('conexiones: PREPARAR -> BUSCAR GLOBAL TIQ -> BUSCAR GLOBAL AME -> BUSCAR historico -> BUSCAR periodos -> CLASIFICAR (directo, sin el detour de carpeta/reporte legacy)', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8'));
  const conns = wf.connections;
  const next = function (n) { return conns[n].main[0][0].node; };
  assert.strictEqual(next('PREPARAR control3_entrada limpio (Python)'), 'BUSCAR GLOBAL oficial CONTROL3 (Drive)');
  assert.strictEqual(next('BUSCAR GLOBAL oficial CONTROL3 (Drive)'), 'BUSCAR GLOBAL AME oficial CONTROL3 (Drive)');
  assert.strictEqual(next('BUSCAR GLOBAL AME oficial CONTROL3 (Drive)'), 'BUSCAR historico CxC/CxP maestro (Drive)');
  assert.strictEqual(next('BUSCAR periodos CxC/CxP maestro (Drive)'), 'CLASIFICAR - Artefactos de CONTROL 3 en Drive');
});
test('conexiones: INTERPRETAR resultado control3 responde directo (el publish-oficial legacy queda desconectado, no aplica al shape institucional)', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8'));
  assert.strictEqual(wf.connections['INTERPRETAR resultado control3'].main[0][0].node, 'RESPONDER control3');
});

console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

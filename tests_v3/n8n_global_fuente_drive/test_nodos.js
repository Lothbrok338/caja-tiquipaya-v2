/**
 * tests_v3/n8n_global_fuente_drive/test_nodos.js -- FASE 12E.3.
 *
 * Ejecuta, con Node puro (sin n8n, sin Drive), el codigo REAL de los nodos Code
 * que materializan la carpeta SAP oficial para GLOBAL. Ademas verifica que ese
 * mismo texto es el que esta desplegado en el snapshot de BACKEND DEV
 * (snapshots/v3-final/aLs1f3GMqswbaENA_backend_dev.json) -- si alguien cambia
 * el workflow sin actualizar estos archivos (o al reves), este test falla.
 *
 * Uso: node tests_v3/n8n_global_fuente_drive/test_nodos.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const dirNodos = path.join(__dirname, 'nodos');
const snapshot = path.join(__dirname, '..', '..', 'snapshots', 'v3-final', 'aLs1f3GMqswbaENA_backend_dev.json');

function cargar(nombre) { return fs.readFileSync(path.join(dirNodos, nombre + '.js'), 'utf8'); }

function ejecutar(codigo, nodos, entradas, env) {
  const $ = function (nombre) {
    if (!(nombre in nodos)) throw new Error('nodo no mockeado: ' + nombre);
    const items = nodos[nombre];
    return { first: function () { return items[0]; }, all: function () { return items; }, item: items[0] };
  };
  const $input = { all: function () { return entradas; }, first: function () { return entradas[0]; } };
  return new Function('$', '$input', '$execution', '$env', 'Buffer', codigo)($, $input, { id: 'test-1' }, env || {}, Buffer);
}

let pasados = 0, fallidos = 0;
function test(nombre, fn) {
  try { fn(); pasados++; console.log('PASS - ' + nombre); }
  catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); }
}

const webhook = function (anio, mes, caja) { return { 'WEBHOOK global': [{ json: { body: { anio: anio, mes: mes, caja: caja } } }] }; };
const SEP = { anio: 2026, mes: 9, periodo: '2026-09', caja: 'tiquipaya', dir_entrada: '/base/global_entrada/2026-09' };
const drive = function (nombres) { return nombres.map(function (n, i) { return { json: { id: 'id' + i + '_' + n, name: n } }; }); };
const filtrar = function (nombres, caja) {
  const resuelto = Object.assign({}, SEP, caja === 'america'
    ? { caja: 'america', dir_entrada: '/base/global_entrada/america/2026-09' }
    : { caja: caja || 'tiquipaya' });
  return ejecutar(cargar('filtrar'), { 'RESOLVER carpeta SAP oficial': [{ json: resuelto }] }, drive(nombres)).map(function (i) { return i.json; });
};
const SEPT_REAL = ['SAP_TIQ_10-09-2026.xlsx', 'SAP_09-09-2026.xlsx', 'SAP_08-09-2026.xlsx', 'SAP_07-09-2026.xlsx',
  'SAP_05-09-2026.xlsx', 'SAP_04-09-2026.xlsx', 'SAP_03-09-2026.xlsx', 'SAP_02-09-2026.xlsx', 'SAP_01-09-2026.xlsx'];

test('resolver: septiembre 2026 -> carpeta oficial + dir aislado global_entrada/2026-09', function () {
  const r = ejecutar(cargar('resolver'), webhook(2026, 9), [])[0].json;
  assert.strictEqual(r.periodo, '2026-09');
  assert.strictEqual(r.carpeta_sap_id, '1mid4gUHnCmZbISlsAYMwWta3RudTSE13');
  assert.ok(r.dir_entrada.endsWith('/dev_workdir/global_entrada/2026-09'));
  assert.ok(!r.dir_entrada.includes('publicacion'));
  const prep = JSON.parse(Buffer.from(r.input_b64, 'base64').toString('utf8'));
  assert.deepStrictEqual([prep.anio, prep.mes], [2026, 9]);
});
// FASE 12F -- aislamiento por CAJA: carpeta_sap_id ya no depende de un mapa
// por periodo (CARPETAS_SAP_OFICIALES); se resuelve por caja (env
// DRIVE_SAP_TIQ/AME), mismo patron que config_drive_oficial.py.
// carpeta_controles_id (05_CONTROLES, historico maestro compartido) es
// INSTITUCIONAL: la misma carpeta para las dos cajas. Cualquier periodo
// valido resuelve, no solo 2026-09.
test('resolver: TIQUIPAYA en un periodo cualquiera usa los folder IDs historicos (sin mapa por periodo)', function () {
  const r = ejecutar(cargar('resolver'), webhook(2026, 10), [])[0].json;
  assert.strictEqual(r.periodo, '2026-10');
  assert.strictEqual(r.caja, 'tiquipaya');
  assert.strictEqual(r.carpeta_sap_id, '1mid4gUHnCmZbISlsAYMwWta3RudTSE13');
  assert.strictEqual(r.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
});
test('resolver: caja ausente en el body -> default tiquipaya (rutas historicas intactas, sin /america/)', function () {
  const r = ejecutar(cargar('resolver'), webhook(2026, 9), [])[0].json;
  assert.strictEqual(r.caja, 'tiquipaya');
  assert.strictEqual(r.dir_entrada, '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir/global_entrada/2026-09');
  assert.ok(!r.dir_entrada.includes('/america/'));
  const prep = JSON.parse(Buffer.from(r.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(prep.caja, 'tiquipaya');
});
test('resolver: caja="america" sin DRIVE_SAP_AME configurada -> falla cerrado (DRIVE_AME_PENDIENTE), nunca hereda el SAP de TIQ', function () {
  assert.throws(function () { ejecutar(cargar('resolver'), webhook(2026, 9, 'america'), []); }, /DRIVE_AME_PENDIENTE.*DRIVE_SAP_AME/);
});
test('resolver: caja="america" con DRIVE_SAP_AME -> sap distinto de TIQ, dir_entrada bajo /america/, PERO carpeta_controles_id institucional identica a TIQ', function () {
  const env = { DRIVE_SAP_AME: 'ame-sap-1' };
  const r = ejecutar(cargar('resolver'), webhook(2026, 9, 'america'), [], env)[0].json;
  assert.strictEqual(r.caja, 'america');
  assert.strictEqual(r.carpeta_sap_id, 'ame-sap-1');
  assert.strictEqual(r.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.notStrictEqual(r.carpeta_sap_id, '1mid4gUHnCmZbISlsAYMwWta3RudTSE13');
  assert.strictEqual(r.dir_entrada, '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir/global_entrada/america/2026-09');
  const prep = JSON.parse(Buffer.from(r.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(prep.caja, 'america');
});
test('resolver: caja invalida ("brasil") falla cerrado con CAJA_DESCONOCIDA', function () {
  assert.throws(function () { ejecutar(cargar('resolver'), webhook(2026, 9, 'brasil'), []); }, /CAJA_DESCONOCIDA/);
});
test('resolver: anio/mes invalidos (string, fuera de rango, ausentes) fallan', function () {
  [[ '2026', 9 ], [2026, 13], [2026, 0], [1999, 9], [undefined, 9], [2026, 9.5]].forEach(function (p) {
    assert.throws(function () { ejecutar(cargar('resolver'), webhook(p[0], p[1]), []); }, /PERIODO_INVALIDO/);
  });
});
test('filtrar: los 9 SAP reales de septiembre (8 legacy + 1 V3), en orden cronologico', function () {
  const r = filtrar(SEPT_REAL);
  assert.strictEqual(r.length, 9);
  assert.deepStrictEqual(r.map(function (x) { return x.fecha; }),
    ['2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-05', '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10']);
  assert.strictEqual(r[0].origen, 'legacy');
  assert.strictEqual(r[8].origen, 'v3');
  assert.ok(r.every(function (x) { return x.hay_sap === true && x.cantidad === 9; }));
});
test('filtrar AMERICA: acepta solo SAP_AME y rechaza SAP_TIQ y legacy TIQ', function () {
  const r = filtrar([
    'SAP_AME_01-09-2026.xlsx',
    'SAP_TIQ_02-09-2026.xlsx',
    'SAP_03-09-2026.xlsx',
    'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx',
  ], 'america');
  assert.deepStrictEqual(r.map(function (x) { return x.name; }), ['SAP_AME_01-09-2026.xlsx']);
  assert.strictEqual(r[0].ruta_destino, '/base/global_entrada/america/2026-09/SAP_AME_01-09-2026.xlsx');
});
test('filtrar TIQUIPAYA: conserva compatibilidad SAP_TIQ y legacy TIQ, rechaza SAP_AME', function () {
  const r = filtrar(['SAP_TIQ_01-09-2026.xlsx', 'SAP_02-09-2026.xlsx', 'SAP_AME_03-09-2026.xlsx'], 'tiquipaya');
  assert.deepStrictEqual(r.map(function (x) { return x.name; }), ['SAP_TIQ_01-09-2026.xlsx', 'SAP_02-09-2026.xlsx']);
});
test('filtrar: caja desconocida falla cerrado', function () {
  assert.throws(function () { filtrar(['SAP_TIQ_01-09-2026.xlsx'], 'brasil'); }, /CAJA_DESCONOCIDA/);
});
test('filtrar: cada SAP conserva su propio fileId y su ruta de destino', function () {
  const r = filtrar(SEPT_REAL);
  r.forEach(function (x) {
    assert.strictEqual(x.id, 'id' + SEPT_REAL.indexOf(x.name) + '_' + x.name);
    assert.strictEqual(x.ruta_destino, '/base/global_entrada/2026-09/' + x.name);
  });
  assert.strictEqual(new Set(r.map(function (x) { return x.id; })).size, 9);
});
test('filtrar: excluye SAP_GLOBAL, otro mes, otro anio, temporales y ajenos', function () {
  const r = filtrar(SEPT_REAL.concat(['SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', 'SAP_TIQ_01-08-2026.xlsx', 'SAP_01-09-2027.xlsx',
    '~$SAP_01-09-2026.xlsx', '.SAP_02-09-2026.xlsx', 'SAP_03-09-2026.xlsx.tmp', 'RESULTADO_GLOBAL_TIQ_SEPTIEMBRE_2026.json',
    'notas.txt', 'SAP_31-09-2026.xlsx']));
  assert.strictEqual(r.length, 9);
});
test('filtrar: SAP_11-09 nuevo en Drive se incluye (10 SAP)', function () {
  assert.strictEqual(filtrar(SEPT_REAL.concat(['SAP_TIQ_11-09-2026.xlsx'])).length, 10);
});
test('filtrar: dos archivos con el mismo nombre exacto en Drive -> ERROR_AMBIGUO_SAP_DRIVE', function () {
  assert.throws(function () { filtrar(SEPT_REAL.concat(['SAP_01-09-2026.xlsx'])); }, /ERROR_AMBIGUO_SAP_DRIVE.*SAP_01-09-2026\.xlsx/);
});
test('filtrar: misma fecha con nombres distintos pasa (Python decide dedup/ambiguedad por contenido)', function () {
  const r = filtrar(['SAP_10-09-2026.xlsx', 'SAP_TIQ_10-09-2026.xlsx']);
  assert.strictEqual(r.length, 2);
});
test('filtrar: carpeta vacia o item vacio ({}) -> hay_sap=false (nunca cuelga la cadena)', function () {
  assert.deepStrictEqual(filtrar([]), [{ hay_sap: false, cantidad: 0 }]);
  const r = ejecutar(cargar('filtrar'), { 'RESOLVER carpeta SAP oficial': [{ json: SEP }] }, [{ json: {} }]).map(function (i) { return i.json; });
  assert.deepStrictEqual(r, [{ hay_sap: false, cantidad: 0 }]);
});
test('resolver: expone la carpeta 05_CONTROLES y el nombre del historico maestro (guardia de cierre)', function () {
  const r = ejecutar(cargar('resolver'), webhook(2026, 9), [])[0].json;
  assert.strictEqual(r.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.strictEqual(r.nombre_historico, 'HISTORICO_ASIGNACIONES.csv');
});
const verificarHist = function (items) {
  return ejecutar(cargar('verificar_historico'), { 'RESOLVER carpeta SAP oficial': [{ json: Object.assign({ nombre_historico: 'HISTORICO_ASIGNACIONES.csv' }, SEP) }],
    'BUSCAR historico CONTROL1 (guardia de cierre)': items }, [])[0].json;
};
test('guardia: historico 0 -> hay_historico=false; 1 -> id; >1 -> ERROR_AMBIGUO_HISTORICO; ignora otros nombres/vacio', function () {
  assert.deepStrictEqual(verificarHist([{ json: {} }]), { hay_historico: false, historico_id: null });
  assert.deepStrictEqual(verificarHist([{ json: { id: 'h1', name: 'HISTORICO_ASIGNACIONES.csv' } }, { json: { id: 'x', name: 'HISTORICO_ASIGNACIONES_old.csv' } }]),
    { hay_historico: true, historico_id: 'h1' });
  assert.throws(function () { verificarHist([{ json: { id: 'a', name: 'HISTORICO_ASIGNACIONES.csv' } }, { json: { id: 'b', name: 'HISTORICO_ASIGNACIONES.csv' } }]); }, /ERROR_AMBIGUO_HISTORICO/);
});
test('restaurar: devuelve el item original del webhook (body.anio/mes intactos)', function () {
  const w = webhook(2026, 9);
  const r = ejecutar(cargar('restaurar'), w, [{ json: { hay_sap: true } }]);
  assert.deepStrictEqual(r[0].json, w['WEBHOOK global'][0].json);
});
test('sin ninguna referencia a publicacion/sap ni $input.first() para elegir archivos', function () {
  ['resolver', 'filtrar', 'restaurar', 'verificar_historico'].forEach(function (n) {
    const c = cargar(n);
    assert.ok(!/publicacion/.test(c), n + ' no debe mencionar publicacion/');
  });
  assert.ok(!/\$input\.first\(\)/.test(cargar('filtrar')));
});
test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8')); const nodos = (wf.workflow || wf).nodes;
  const mapa = { 'RESOLVER carpeta SAP oficial': 'resolver', 'FILTRAR - SAP diarios validos del periodo': 'filtrar', 'RESTAURAR - Item del webhook global': 'restaurar',
    'RESTAURAR 2 - Item del webhook global': 'restaurar', 'VERIFICAR historico (guardia de cierre)': 'verificar_historico' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    if (!nodo) { console.log('       (nodo ' + nombre + ' aun no esta en el snapshot)'); assert.fail('falta nodo ' + nombre); }
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), 'desalineado: ' + nombre);
  });
});

console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

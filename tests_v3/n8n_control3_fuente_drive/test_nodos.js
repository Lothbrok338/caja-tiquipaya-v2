/**
 * tests_v3/n8n_control3_fuente_drive/test_nodos.js -- FASE 12E.7.
 *
 * Ejecuta, con Node puro (sin n8n ni Drive), el codigo REAL de los nodos Code que materializan las entradas de
 * CONTROL 3 desde Drive y deciden que se publica, y verifica que ese mismo texto es el desplegado en el snapshot
 * de BACKEND DEV.
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

function ejecutar(codigo, nodos, entradas, json) {
  const $ = function (nombre) {
    if (!(nombre in nodos)) throw new Error('nodo no mockeado: ' + nombre);
    const items = nodos[nombre];
    return { first: function () { return items[0]; }, all: function () { return items; } };
  };
  const $input = { all: function () { return entradas || []; }, first: function () { return (entradas || [])[0]; } };
  return new Function('$', '$input', '$json', '$execution', 'Buffer', codigo)($, $input, json || {}, { id: 'test-1' }, Buffer);
}
let pasados = 0, fallidos = 0;
function test(nombre, fn) {
  try { fn(); pasados++; console.log('PASS - ' + nombre); }
  catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); }
}

const WH = function (body) { return { 'WEBHOOK control3': [{ json: { body: body } }] }; };
const RC = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, modo: 'official' }))[0].json;
const NODOS_C = function (g, h, p, r) {
  const mk = function (pref, arr) { return arr.map(function (n, i) { return { json: n === null ? {} : { id: pref + i, name: n } }; }); };
  return {
    'RESOLVER control3 (periodo y carpetas)': [{ json: RC }],
    'BUSCAR GLOBAL oficial CONTROL3 (Drive)': mk('g', g),
    'BUSCAR historico CxC/CxP maestro (Drive)': mk('h', h),
    'BUSCAR periodos CxC/CxP maestro (Drive)': mk('p', p),
    'BUSCAR reporte del periodo CONTROL3 (Drive)': mk('r', r),
  };
};
const G = 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', H = 'HISTORICO_CXC_CXP.csv', P = 'HISTORICO_CXC_CXP_PERIODOS.json', R = 'CONTROL_CXC_CXP_SEPTIEMBRE_2026.xlsx';
const clasificar = function (g, h, p, r) { return ejecutar(cargar('clasificar'), NODOS_C(g, h, p, r), []).map(function (i) { return i.json; }); };

test('resolver: septiembre 2026 -> nombres, dir aislado control3_entrada/2026-09 y carpetas de Drive', function () {
  assert.strictEqual(RC.periodo, '2026-09');
  assert.strictEqual(RC.nombre_global, G);
  assert.strictEqual(RC.nombre_historico, H);
  assert.strictEqual(RC.nombre_periodos, P);
  assert.strictEqual(RC.nombre_reporte, R);
  assert.strictEqual(RC.nombre_reporte_json, 'CONTROL_CXC_CXP_SEPTIEMBRE_2026.json');
  assert.ok(RC.dir_entrada.endsWith('/dev_workdir/control3_entrada/2026-09'));
  assert.ok(!/\/global\/|publicacion/.test(RC.dir_entrada));
  assert.strictEqual(RC.carpeta_global_id, '1KREzDpgptWRwuArA1qYco49rplOEeeNU');
  assert.strictEqual(RC.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.strictEqual(RC.carpeta_control3_id, '15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_');
});
test('resolver: anio/mes invalidos -> PERIODO_INVALIDO', function () {
  [{ anio: 2026, mes: 13 }, { anio: '2026', mes: 9 }, { anio: 1999, mes: 9 }, {}].forEach(function (b) {
    assert.throws(function () { ejecutar(cargar('resolver'), WH(b)); }, /PERIODO_INVALIDO/);
  });
});
test('clasificar: GLOBAL + maestros + reporte de Drive -> 4 descargas en control3_entrada', function () {
  const r = clasificar([G], [H], [P], [R]);
  assert.deepStrictEqual(r.map(function (i) { return i.tipo; }), ['global', 'historico', 'periodos', 'reporte']);
  r.forEach(function (i) { assert.strictEqual(i.ruta_destino, RC.dir_entrada + '/' + i.name); });
});
test('clasificar: primera ejecucion (sin maestros ni reporte) -> solo GLOBAL', function () {
  const r = clasificar([G], [null], [null], [null]);
  assert.deepStrictEqual(r.map(function (i) { return i.tipo; }), ['global']);
  assert.strictEqual(r[0].maestros_en_drive, false);
});
test('clasificar: GLOBAL ausente -> GLOBAL_OFICIAL_NO_ENCONTRADO; duplicados -> ERROR_AMBIGUO_*', function () {
  assert.throws(function () { clasificar([null], [H], [P], [null]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
  assert.throws(function () { clasificar([G, G], [H], [P], [null]); }, /ERROR_AMBIGUO_GLOBAL/);
  assert.throws(function () { clasificar([G], [H, H], [P], [null]); }, /ERROR_AMBIGUO_HISTORICO/);
  assert.throws(function () { clasificar([G], [H], [P, P], [null]); }, /ERROR_AMBIGUO_PERIODOS/);
  assert.throws(function () { clasificar([G], [H], [P], [R, R]); }, /ERROR_AMBIGUO_REPORTE/);
});
test('clasificar: historico sin libro de periodos (o al reves) -> MAESTROS_CXC_CXP_INCOMPLETOS', function () {
  assert.throws(function () { clasificar([G], [H], [null], [null]); }, /MAESTROS_CXC_CXP_INCOMPLETOS/);
  assert.throws(function () { clasificar([G], [null], [P], [null]); }, /MAESTROS_CXC_CXP_INCOMPLETOS/);
});
test('clasificar: ignora archivos con otro nombre (snapshots/otros periodos nunca son fuente)', function () {
  const r = clasificar([G, 'SAP_GLOBAL_TIQ_AGOSTO_2026.xlsx'], [H, 'HISTORICO_CXC_CXP_2026-08.csv'], [P], [R, 'CONTROL_CXC_CXP_AGOSTO_2026.xlsx']);
  assert.deepStrictEqual(r.map(function (i) { return i.name; }), [G, H, P, R]);
});
test('verificar_carpeta: 0 -> periodo nuevo; 1 -> id; >1 -> ERROR_AMBIGUO_CARPETA_PERIODO', function () {
  const v = function (items) { return ejecutar(cargar('verificar_carpeta'), { 'RESOLVER control3 (periodo y carpetas)': [{ json: RC }], 'BUSCAR carpeta del periodo CONTROL3 (Drive)': items }, [])[0].json; };
  assert.deepStrictEqual(v([{ json: {} }]), { hay_carpeta: false, carpeta_id: null });
  assert.deepStrictEqual(v([{ json: { id: 'c1', name: '2026-09' } }, { json: { id: 'c0', name: '2026-08' } }]), { hay_carpeta: true, carpeta_id: 'c1' });
  assert.throws(function () { v([{ json: { id: 'a', name: '2026-09' } }, { json: { id: 'b', name: '2026-09' } }]); }, /ERROR_AMBIGUO_CARPETA_PERIODO/);
});
test('restaurar: devuelve el item original del webhook', function () {
  const w = WH({ anio: 2026, mes: 9 });
  assert.deepStrictEqual(ejecutar(cargar('restaurar'), w, [{ json: { x: 1 } }])[0].json, w['WEBHOOK control3'][0].json);
});

const payload = function (body) {
  const p = ejecutar(cargar('construir_payload'), WH(Object.assign({ anio: 2026, mes: 9, modo: 'official' }, body)))[0].json;
  return JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
};
test('payload: preliminar por defecto; cierre solo con modo_control3=cerrar; confirmacion solo si es true', function () {
  assert.deepStrictEqual([payload({}).modo_control3, payload({}).confirmacion_cierre], ['preliminar', false]);
  assert.deepStrictEqual([payload({ modo_control3: 'cerrar' }).modo_control3, payload({ modo_control3: 'cerrar' }).confirmacion_cierre], ['cerrar', false]);
  const c = payload({ modo_control3: 'cerrar', confirmacion_cierre: true });
  assert.deepStrictEqual([c.modo_control3, c.confirmacion_cierre], ['cerrar', true]);
  assert.strictEqual(payload({ modo_control3: 'cerrar', confirmacion_cierre: 'true' }).confirmacion_cierre, false);
  assert.ok(!/\.item\b/.test(cargar('construir_payload')) && !/\.item\b/.test(cargar('decidir_publicar')));
});

const RESULT_BASE = { modo_control3: 'preliminar', estado: 'OK', estado_control3: 'PRELIMINAR_OK', dry_run: false, historico_actualizado: false, periodos_actualizado: false,
  archivo_control_xlsx: RC.dir_entrada + '/' + R, archivo_control_json: RC.dir_entrada + '/' + RC.nombre_reporte_json };
const decidir = function (r, modo) {
  return ejecutar(cargar('decidir_publicar'), Object.assign({ 'RESOLVER control3 (periodo y carpetas)': [{ json: RC }] }, WH({ anio: 2026, mes: 9, modo: modo || 'official' })), [], { data: r })[0].json;
};
const CERRADO = Object.assign({}, RESULT_BASE, { modo_control3: 'cerrar', estado_control3: 'CERRADO', historico_actualizado: true, periodos_actualizado: true });
test('PRELIMINAR: publica solo reporte (xlsx+json); nunca historico, libro ni snapshots', function () {
  const d = decidir(RESULT_BASE);
  assert.deepStrictEqual([d.debe_publicar, d.hay_reporte, d.hay_reporte_json, d.hay_snapshots, d.hay_historico, d.hay_periodos], [true, true, true, false, false, false]);
  // aunque un resultado (falso) de preliminar dijera que actualizo los maestros, NO se publican
  const falso = decidir(Object.assign({}, RESULT_BASE, { historico_actualizado: true, periodos_actualizado: true, estado_control3: 'CERRADO' }));
  assert.deepStrictEqual([falso.hay_historico, falso.hay_periodos, falso.hay_snapshots], [false, false, false]);
});
test('CIERRE exitoso: publica reporte, snapshots del periodo, historico y libro maestros', function () {
  const d = decidir(CERRADO);
  assert.deepStrictEqual([d.debe_publicar, d.hay_reporte, d.hay_reporte_json, d.hay_snapshots, d.hay_historico, d.hay_periodos], [true, true, true, true, true, true]);
});
test('CIERRE: YA_CERRADO / bloqueado / error / simulacro -> nada se publica', function () {
  const nada = function (mut) { const d = decidir(Object.assign({}, CERRADO, mut)); assert.deepStrictEqual([d.debe_publicar, d.hay_historico, d.hay_periodos, d.hay_snapshots], [false, false, false, false], JSON.stringify(mut)); };
  nada({ estado_control3: 'YA_CERRADO', historico_actualizado: false, periodos_actualizado: false, archivo_control_xlsx: null, archivo_control_json: null });
  nada({ estado_control3: 'CIERRE_BLOQUEADO', historico_actualizado: false, periodos_actualizado: false, archivo_control_xlsx: null, archivo_control_json: null });
  nada({ estado_control3: 'CIERRE_BLOQUEADO_OBSERVACIONES', historico_actualizado: false, periodos_actualizado: false, archivo_control_xlsx: null, archivo_control_json: null });
  nada({ estado: 'ERROR_TECNICO', archivo_control_xlsx: null, archivo_control_json: null });
  nada({ dry_run: true });
  assert.strictEqual(decidir({ resultado: 'ERROR', codigo: 'RuntimeError', mensaje: 'x' }).debe_publicar, false);
});
test('CIERRE recuperado (solo se sello el libro): publica snapshots y libro, no el historico', function () {
  const d = decidir(Object.assign({}, CERRADO, { historico_actualizado: false, archivo_control_xlsx: null, archivo_control_json: null }));
  assert.deepStrictEqual([d.hay_reporte, d.hay_snapshots, d.hay_historico, d.hay_periodos], [false, true, false, true]);
});
test('reporte con nombre de otro periodo -> no se publica; modo dev -> nada', function () {
  assert.strictEqual(decidir(Object.assign({}, RESULT_BASE, { archivo_control_xlsx: RC.dir_entrada + '/CONTROL_CXC_CXP_AGOSTO_2026.xlsx' })).hay_reporte, false);
  assert.strictEqual(decidir(CERRADO, 'dev').debe_publicar, false);
});

const lista = function (d, carpeta) {
  return ejecutar(cargar('lista_publicaciones'), { 'DECIDIR - Publicar CONTROL3 oficial': [{ json: d }], 'RESOLVER control3 (periodo y carpetas)': [{ json: RC }],
    'EJECUTAR 07E carpeta del periodo CONTROL3': [{ json: { carpeta_id: carpeta === undefined ? 'CP' : carpeta } }] }, []).map(function (i) { return i.json; });
};
test('lista: preliminar -> 2 archivos en la carpeta del periodo, ninguno en la raiz de 05_CONTROLES', function () {
  const l = lista(decidir(RESULT_BASE));
  assert.deepStrictEqual(l.map(function (i) { return i.nombre_archivo; }), [R, RC.nombre_reporte_json]);
  l.forEach(function (i) { assert.strictEqual(i.carpeta_id, 'CP'); assert.strictEqual(i.modo_si_existe, 'actualizar'); });
});
test('lista: cierre -> orden reporte, json, snapshots, historico maestro, libro maestro SIEMPRE al final', function () {
  const l = lista(decidir(CERRADO));
  assert.deepStrictEqual(l.map(function (i) { return i.carpeta_id + ':' + i.nombre_archivo; }),
    ['CP:' + R, 'CP:' + RC.nombre_reporte_json, 'CP:' + H, 'CP:' + P, RC.carpeta_controles_id + ':' + H, RC.carpeta_controles_id + ':' + P]);
  l.forEach(function (i) { assert.strictEqual(i.ruta_local_origen, RC.dir_entrada + '/' + i.nombre_archivo); });
  assert.throws(function () { lista(decidir(CERRADO), null); }, /CARPETA_PERIODO_CONTROL3_NO_RESUELTA/);
});
test('ningun nodo usa dev_workdir/global/ ni publicacion/ como fuente', function () {
  ['resolver', 'clasificar', 'verificar_carpeta', 'restaurar', 'construir_payload', 'decidir_publicar', 'lista_publicaciones'].forEach(function (n) {
    assert.ok(!/dev_workdir\/global\/|publicacion\//.test(cargar(n)), n);
  });
});
test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8')); const nodos = (wf.workflow || wf).nodes;
  const mapa = { 'RESOLVER control3 (periodo y carpetas)': 'resolver', 'VERIFICAR carpeta del periodo (CONTROL3)': 'verificar_carpeta',
    'CLASIFICAR - Artefactos de CONTROL 3 en Drive': 'clasificar', 'RESTAURAR - Item del webhook control3': 'restaurar',
    'CONSTRUIR payload control3': 'construir_payload', 'DECIDIR - Publicar CONTROL3 oficial': 'decidir_publicar', 'CONSTRUIR - Lista publicaciones CONTROL3': 'lista_publicaciones' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    if (!nodo) assert.fail('falta nodo ' + nombre);
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), nombre);
  });
});

console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

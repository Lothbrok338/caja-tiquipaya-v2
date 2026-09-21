/**
 * tests_v3/n8n_control1_fuente_drive/test_nodos.js -- FASE 12F (institucional).
 *
 * Ejecuta, con Node puro (sin n8n ni Drive), el codigo REAL de los nodos Code que
 * materializan las entradas de CONTROL 1 INSTITUCIONAL desde Drive (AMBOS GLOBAL,
 * TIQ y AME, del mismo periodo, nunca por caja) y verifica que ese mismo texto es
 * el desplegado en el snapshot de BACKEND DEV.
 *
 * Uso: node tests_v3/n8n_control1_fuente_drive/test_nodos.js
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

const WH = function (body) { return { 'WEBHOOK control1': [{ json: { body: body } }] }; };
const RC = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9 }))[0].json;
const G_TIQ = 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', G_AME = 'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx';
const H = 'HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv';
const NODOS_C = function (gTiq, gAme, h) {
  return {
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
    'BUSCAR GLOBAL oficial (Drive)': gTiq.map(function (n, i) { return { json: n === null ? {} : { id: 'gt' + i, name: n } }; }),
    'BUSCAR GLOBAL AME oficial (Drive)': gAme.map(function (n, i) { return { json: n === null ? {} : { id: 'ga' + i, name: n } }; }),
    'BUSCAR historico asignaciones (Drive)': h.map(function (n, i) { return { json: n === null ? {} : { id: 'h' + i, name: n } }; }),
  };
};
const clasificar = function (gTiq, gAme, h) { return ejecutar(cargar('clasificar'), NODOS_C(gTiq, gAme, h), []).map(function (i) { return i.json; }); };

test('resolver: septiembre 2026 -> nombres TIQ+AME, dir aislado control1_institucional_entrada/2026-09', function () {
  assert.strictEqual(RC.periodo, '2026-09');
  assert.strictEqual(RC.nombre_global_tiq, G_TIQ);
  assert.strictEqual(RC.nombre_global_ame, G_AME);
  assert.strictEqual(RC.nombre_historico, H);
  assert.ok(RC.dir_entrada.endsWith('/dev_workdir/control1_institucional_entrada/2026-09'));
  assert.ok(!/\/global\/|publicacion|\/america\//.test(RC.dir_entrada));
  assert.strictEqual(RC.carpeta_global_id, '1KREzDpgptWRwuArA1qYco49rplOEeeNU');
  assert.strictEqual(RC.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.strictEqual(RC.carpeta_control1_id, '1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk');
});
test('resolver: nunca lee `caja` del body -- CONTROL 1 institucional no depende del selector', function () {
  assert.ok(!('caja' in RC));
  const conCaja = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, caja: 'america' }))[0].json;
  // El body puede traer `caja` (el frontend actual no la manda, pero si llegara,
  // el resolver institucional la ignora por completo: ambos nombres son fijos).
  assert.strictEqual(conCaja.nombre_global_tiq, G_TIQ);
  assert.strictEqual(conCaja.nombre_global_ame, G_AME);
  assert.ok(!('caja' in conCaja));
});
test('resolver: los 12 meses generan los nombres canonicos TIQ+AME (mismo que consolidador_mensual)', function () {
  const esperados = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'];
  esperados.forEach(function (m, i) {
    const r = ejecutar(cargar('resolver'), WH({ anio: 2027, mes: i + 1 }))[0].json;
    assert.strictEqual(r.nombre_global_tiq, 'SAP_GLOBAL_TIQ_' + m + '_2027.xlsx');
    assert.strictEqual(r.nombre_global_ame, 'SAP_GLOBAL_AME_' + m + '_2027.xlsx');
  });
});
test('resolver: anio/mes invalidos fallan', function () {
  [['2026', 9], [2026, 13], [2026, 0], [1999, 9], [undefined, 9], [2026, 9.5]].forEach(function (p) {
    assert.throws(function () { ejecutar(cargar('resolver'), WH({ anio: p[0], mes: p[1] })); }, /PERIODO_INVALIDO/);
  });
});
test('A: ambos GLOBAL oficiales existen (con historico institucional) -> los 3 se descargan a control1_institucional_entrada', function () {
  const r = clasificar([G_TIQ], [G_AME], [H]);
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global_tiq', 'global_ame', 'historico']);
  r.forEach(function (x) { assert.ok(x.ruta_destino.startsWith(RC.dir_entrada + '/')); });
  assert.strictEqual(r[0].id, 'gt0');
  assert.strictEqual(r[1].id, 'ga0');
});
test('B: nombres parecidos/no exactos en la carpeta GLOBAL se ignoran (solo el exacto cuenta)', function () {
  const r = clasificar(['SAP_GLOBAL_TIQ_SEPTIEMBRE_2026_copia.xlsx', G_TIQ, 'SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx'], [G_AME], [null]);
  assert.strictEqual(r.filter(function (x) { return x.tipo === 'global_tiq'; }).length, 1);
  assert.strictEqual(r.find(function (x) { return x.tipo === 'global_tiq'; }).name, G_TIQ);
});
test('C: falta el GLOBAL TIQ (busqueda vacia) -> GLOBAL_OFICIAL_NO_ENCONTRADO', function () {
  assert.throws(function () { clasificar([null], [G_AME], [H]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
});
test('C2: falta el GLOBAL AME (busqueda vacia) -> GLOBAL_OFICIAL_NO_ENCONTRADO', function () {
  assert.throws(function () { clasificar([G_TIQ], [null], [H]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
});
test('D: mas de un GLOBAL TIQ exacto -> ERROR_AMBIGUO_GLOBAL', function () {
  assert.throws(function () { clasificar([G_TIQ, G_TIQ], [G_AME], [H]); }, /ERROR_AMBIGUO_GLOBAL/);
});
test('D2: mas de un GLOBAL AME exacto -> ERROR_AMBIGUO_GLOBAL', function () {
  assert.throws(function () { clasificar([G_TIQ], [G_AME, G_AME], [H]); }, /ERROR_AMBIGUO_GLOBAL/);
});
test('E: historico institucional en Drive existe -> se descarga', function () {
  const r = clasificar([G_TIQ], [G_AME], [H]);
  assert.ok(r.some(function (x) { return x.tipo === 'historico'; }));
  assert.strictEqual(r[0].historico_en_drive, true);
});
test('G: historico institucional inexistente en Drive -> primera ejecucion legitima (no se descarga, flag false)', function () {
  const r = clasificar([G_TIQ], [G_AME], [null]);
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global_tiq', 'global_ame']);
  assert.strictEqual(r[0].historico_en_drive, false);
});
test('H: mas de un historico institucional -> ERROR_AMBIGUO_HISTORICO', function () {
  assert.throws(function () { clasificar([G_TIQ], [G_AME], [H, H]); }, /ERROR_AMBIGUO_HISTORICO/);
});
test('clasificar: nunca busca en el nodo Drive de revision (eso es del flujo legacy por-caja)', function () {
  const c = cargar('clasificar');
  assert.ok(!/BUSCAR revision del periodo \(Drive\)/.test(c));
});
test('restaurar/construir_payload usan $(...).first() (no .item) y leen body.anio/mes', function () {
  const w = WH({ anio: 2026, mes: 9 });
  assert.deepStrictEqual(ejecutar(cargar('restaurar'), w)[0].json, w['WEBHOOK control1'][0].json);
  const p = ejecutar(cargar('construir_payload'), w)[0].json;
  const payload = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.deepStrictEqual([payload.anio, payload.mes], [2026, 9]);
  assert.ok(!/\.item\b/.test(cargar('construir_payload')));
});
test('construir_payload: nunca lee `caja` del body -- sin fallback a tiquipaya', function () {
  assert.ok(!/body\.caja|t\.caja|'caja'/.test(cargar('construir_payload')));
});
test('construir_payload: PRELIMINAR por defecto (confirmacion_cierre=false, dry_run=false salvo que el body lo pida)', function () {
  const payload = function (body) {
    const p = ejecutar(cargar('construir_payload'), WH(Object.assign({ anio: 2026, mes: 9 }, body)))[0].json;
    return JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  };
  assert.deepStrictEqual([payload({}).confirmacion_cierre, payload({}).dry_run], [false, false]);
  assert.strictEqual(payload({ confirmacion_cierre: true }).confirmacion_cierre, true);
  // El cierre NUNCA se infiere de otra cosa que no sea el booleano explicito.
  assert.strictEqual(payload({ confirmacion_cierre: 'true' }).confirmacion_cierre, false);
  assert.strictEqual(payload({ confirmacion_cierre: 1 }).confirmacion_cierre, false);
});
test('construir_payload: sin correcciones (o sin confirmacion_cierre) -> comando_ejecutar NUNCA llama a corregir_control1_institucional', function () {
  const comando = function (body) {
    const p = ejecutar(cargar('construir_payload'), WH(Object.assign({ anio: 2026, mes: 9 }, body)))[0].json;
    return p.comando_ejecutar;
  };
  assert.ok(!/corregir_control1_institucional/.test(comando({})));
  assert.ok(!/corregir_control1_institucional/.test(comando({ correcciones_tiq: [[16, 'A', 'B']] })), 'sin confirmacion_cierre, PRELIMINAR nunca aplica correcciones');
  assert.ok(!/corregir_control1_institucional/.test(comando({ confirmacion_cierre: true })), 'confirmacion_cierre sin correcciones no dispara corregir');
});
test('construir_payload: CIERRE con correcciones autorizadas -> comando_ejecutar aplica corregir_control1_institucional ANTES de ejecutar_control1_institucional', function () {
  const p = ejecutar(cargar('construir_payload'), WH({
    anio: 2026, mes: 9, confirmacion_cierre: true,
    correcciones_tiq: [[16, 'MALA_TIQ', 'BUENA_TIQ']], correcciones_ame: [],
  }))[0].json;
  const comando = p.comando_ejecutar;
  assert.ok(/--accion corregir_control1_institucional/.test(comando));
  assert.ok(/--accion ejecutar_control1_institucional/.test(comando));
  assert.ok(comando.indexOf('corregir_control1_institucional') < comando.indexOf('ejecutar_control1_institucional'));
  // El payload de corregir viaja embebido en base64 dentro del propio comando (nunca en texto plano).
  assert.ok(!/MALA_TIQ|BUENA_TIQ/.test(comando));
});
test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8')); const nodos = (wf.workflow || wf).nodes;
  const mapa = { 'RESOLVER control1 (periodo y carpetas)': 'resolver', 'CLASIFICAR - Artefactos de CONTROL 1 en Drive': 'clasificar',
    'RESTAURAR - Item del webhook control1': 'restaurar', 'CONSTRUIR payload control1': 'construir_payload',
    'DECIDIR - Publicar CONTROL1 oficial': 'decidir_publicar', 'CONSTRUIR - Lista publicaciones CONTROL1': 'lista_publicaciones' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    assert.ok(nodo, 'falta nodo ' + nombre);
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), 'desalineado: ' + nombre);
  });
});
test('conexiones: PREPARAR -> BUSCAR GLOBAL TIQ -> BUSCAR GLOBAL AME -> BUSCAR historico -> CLASIFICAR (directo, sin el detour de revision/carpeta legacy)', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8'));
  const conns = wf.connections;
  const next = function (n) { return conns[n].main[0][0].node; };
  assert.strictEqual(next('PREPARAR control1_entrada limpio (Python)'), 'BUSCAR GLOBAL oficial (Drive)');
  assert.strictEqual(next('BUSCAR GLOBAL oficial (Drive)'), 'BUSCAR GLOBAL AME oficial (Drive)');
  assert.strictEqual(next('BUSCAR GLOBAL AME oficial (Drive)'), 'BUSCAR historico asignaciones (Drive)');
  assert.strictEqual(next('BUSCAR historico asignaciones (Drive)'), 'CLASIFICAR - Artefactos de CONTROL 1 en Drive');
});
test('conexiones: INTERPRETAR resultado control1 -> DECIDIR - Publicar CONTROL1 oficial (reconectado al shape institucional, FASE 12G)', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8'));
  assert.strictEqual(wf.connections['INTERPRETAR resultado control1'].main[0][0].node, 'DECIDIR - Publicar CONTROL1 oficial');
});

// ---------------------------------------------------------------------
// FASE 12G -- DECIDIR/CONSTRUIR reconectados al shape institucional
// (TIQ+AME por separado, nunca un tercer GLOBAL combinado).
// ---------------------------------------------------------------------
const RC_PUB = { periodo: '2026-09', nombre_global_tiq: 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', nombre_global_ame: 'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx',
  nombre_historico: 'HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv', nombre_detalle: 'CONTROL_ASIGNACIONES_INSTITUCIONAL_2026-09.json',
  carpeta_global_id: 'GLOBAL_DIR', carpeta_controles_id: 'CONTROLES_DIR', dir_entrada: '/entrada' };
const decidir = function (body, data) {
  return ejecutar(cargar('decidir_publicar'), {
    'WEBHOOK control1': [{ json: { body: body } }],
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC_PUB }],
  }, [], { data: data })[0].json;
};
const listaPub = function (d) {
  return ejecutar(cargar('lista_publicaciones'), {
    'DECIDIR - Publicar CONTROL1 oficial': [{ json: d }],
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC_PUB }],
    'EJECUTAR 07E carpeta del periodo CONTROL1': [{ json: { carpeta_id: 'PERIODO_DIR' } }],
  }, []).map(function (i) { return i.json; });
};

test('PRELIMINAR CONTROL1 no publica maestro ni GLOBAL: solo el detalle/revision del periodo', function () {
  const d = decidir({ modo: 'official' }, { modo: 'preliminar', dry_run: true, historico_actualizado: false, ruta_detalle_json: '/entrada/CONTROL_ASIGNACIONES_INSTITUCIONAL_2026-09.json' });
  assert.deepStrictEqual(d, { debe_publicar: true, hay_detalle: true, hay_historico: false, publicar_global_tiq: false, publicar_global_ame: false });
  const items = listaPub(d);
  assert.deepStrictEqual(items.map(function (i) { return i.nombre_archivo; }), [RC_PUB.nombre_detalle]);
});

test('CIERRE CONTROL1 publica TIQ y AME corregidos cuando ambos cambiaron', function () {
  const d = decidir(
    { modo: 'official', confirmacion_cierre: true, correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[20, 'C', 'D']] },
    { modo: 'cierre', dry_run: false, historico_actualizado: true, ruta_detalle_json: '/entrada/CONTROL_ASIGNACIONES_INSTITUCIONAL_2026-09.json' },
  );
  assert.strictEqual(d.publicar_global_tiq, true);
  assert.strictEqual(d.publicar_global_ame, true);
  assert.strictEqual(d.hay_historico, true);
});

test('CIERRE CONTROL1: si solo cambia AME, TIQ nunca se publica (y viceversa) -- nunca un tercer GLOBAL', function () {
  const d = decidir(
    { modo: 'official', confirmacion_cierre: true, correcciones_tiq: [], correcciones_ame: [[20, 'C', 'D']] },
    { modo: 'cierre', dry_run: false, historico_actualizado: true },
  );
  assert.strictEqual(d.publicar_global_tiq, false);
  assert.strictEqual(d.publicar_global_ame, true);
  const items = listaPub(d);
  assert.ok(!items.some(function (i) { return i.nombre_archivo === RC_PUB.nombre_global_tiq; }));
  assert.ok(items.some(function (i) { return i.nombre_archivo === RC_PUB.nombre_global_ame; }));
  assert.ok(items.every(function (i) { return i.nombre_archivo !== 'SAP_GLOBAL_INSTITUCIONAL.xlsx'; }));
});

test('CONTROL1: el historico MAESTRO (raiz de 05_CONTROLES) va SIEMPRE al final del orden de publicacion', function () {
  const d = decidir(
    { modo: 'official', confirmacion_cierre: true, correcciones_tiq: [[16, 'A', 'B']], correcciones_ame: [[20, 'C', 'D']] },
    { modo: 'cierre', dry_run: false, historico_actualizado: true, ruta_detalle_json: '/entrada/CONTROL_ASIGNACIONES_INSTITUCIONAL_2026-09.json' },
  );
  const items = listaPub(d);
  const ultimo = items[items.length - 1];
  assert.strictEqual(ultimo.nombre_archivo, RC_PUB.nombre_historico);
  assert.strictEqual(ultimo.carpeta_id, RC_PUB.carpeta_controles_id);
  // Los GLOBAL (si los hay) siempre antes que el detalle/historico del periodo.
  const idxTiq = items.findIndex(function (i) { return i.nombre_archivo === RC_PUB.nombre_global_tiq; });
  const idxDetalle = items.findIndex(function (i) { return i.nombre_archivo === RC_PUB.nombre_detalle; });
  assert.ok(idxTiq < idxDetalle);
});

console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

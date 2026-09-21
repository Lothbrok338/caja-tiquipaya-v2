/**
 * tests_v3/n8n_control1_fuente_drive/test_nodos.js -- FASE 12E.4/12G.
 *
 * Ejecuta, con Node puro (sin n8n ni Drive), el codigo REAL de los nodos Code que
 * materializan las entradas de CONTROL 1 INSTITUCIONAL (TIQ+AME) desde Drive y
 * deciden que se publica, y verifica que ese mismo texto es el desplegado en el
 * snapshot de BACKEND DEV.
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
const RC = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, modo: 'official' }))[0].json;
const NODOS_C = function (gTiq, gAme, h, e) {
  return {
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
    'BUSCAR GLOBAL TIQ oficial (Drive)': gTiq.map(function (n, i) { return { json: n === null ? {} : { id: 'gt' + i, name: n } }; }),
    'BUSCAR GLOBAL AME oficial (Drive)': gAme.map(function (n, i) { return { json: n === null ? {} : { id: 'ga' + i, name: n } }; }),
    'BUSCAR historico institucional (Drive)': h.map(function (n, i) { return { json: n === null ? {} : { id: 'h' + i, name: n } }; }),
    'BUSCAR estado del periodo (Drive)': e.map(function (n, i) { return { json: n === null ? {} : { id: 'e' + i, name: n } }; }),
  };
};
const GT = 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', GA = 'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx';
const H = 'HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv', E = 'ESTADO_CONTROL1_INSTITUCIONAL_SEPTIEMBRE_2026.json';
const clasificar = function (gTiq, gAme, h, e) { return ejecutar(cargar('clasificar'), NODOS_C(gTiq, gAme, h, e), []).map(function (i) { return i.json; }); };

test('resolver: septiembre 2026 -> nombres, dir institucional control1_institucional_entrada/2026-09 y carpetas de Drive', function () {
  assert.strictEqual(RC.periodo, '2026-09');
  assert.strictEqual(RC.nombre_global_tiq, GT);
  assert.strictEqual(RC.nombre_global_ame, GA);
  assert.strictEqual(RC.nombre_historico, H);
  assert.strictEqual(RC.nombre_estado, E);
  assert.strictEqual(RC.nombre_detalle, 'CONTROL_ASIGNACIONES_INSTITUCIONAL_SEPTIEMBRE_2026.json');
  assert.ok(RC.dir_entrada.endsWith('/dev_workdir/control1_institucional_entrada/2026-09'));
  assert.ok(!/\/global\/|publicacion/.test(RC.dir_entrada));
  assert.strictEqual(RC.carpeta_global_id, '1KREzDpgptWRwuArA1qYco49rplOEeeNU');
  assert.strictEqual(RC.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.strictEqual(RC.carpeta_control1_id, '1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk');
});
test('resolver: los 12 meses generan los dos nombres canonicos (mismo que consolidador_mensual)', function () {
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
// FASE 12G -- CONTROL 1 nunca recibe ni infiere `caja`: aunque el webhook la
// traiga (compatibilidad hacia atras del payload), se ignora por completo.
test('resolver: nunca depende de `caja` -- presente o ausente, mismos nombres/carpetas/dir_entrada', function () {
  const conCaja = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, caja: 'america' }))[0].json;
  assert.strictEqual(conCaja.nombre_global_tiq, GT);
  assert.strictEqual(conCaja.nombre_global_ame, GA);
  assert.strictEqual(conCaja.dir_entrada, RC.dir_entrada);
  assert.strictEqual(conCaja.carpeta_global_id, RC.carpeta_global_id);
  assert.ok(!('caja' in conCaja));
});
test('A: los dos GLOBAL oficiales existen (con historico y estado) -> los 4 se descargan a control1_institucional_entrada', function () {
  const r = clasificar([GT], [GA], [H], [E]);
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global_tiq', 'global_ame', 'historico', 'estado']);
  r.forEach(function (x) { assert.ok(x.ruta_destino.startsWith(RC.dir_entrada + '/')); });
  assert.strictEqual(r[0].id, 'gt0');
  assert.strictEqual(r[1].id, 'ga0');
});
test('B: nombres parecidos/no exactos en la carpeta GLOBAL se ignoran (solo el exacto cuenta)', function () {
  const r = clasificar(['SAP_GLOBAL_TIQ_SEPTIEMBRE_2026_copia.xlsx', GT, 'SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx'], [GA], [H], [null]);
  assert.strictEqual(r.filter(function (x) { return x.tipo === 'global_tiq'; }).length, 1);
  assert.strictEqual(r.find(function (x) { return x.tipo === 'global_tiq'; }).name, GT);
});
test('C: GLOBAL TIQ inexistente (busqueda vacia {}) -> GLOBAL_OFICIAL_NO_ENCONTRADO', function () {
  assert.throws(function () { clasificar([null], [GA], [H], [E]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
});
test('C2: GLOBAL AME inexistente -> GLOBAL_OFICIAL_NO_ENCONTRADO (no basta con TIQ)', function () {
  assert.throws(function () { clasificar([GT], [null], [H], [E]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
});
test('D: mas de un GLOBAL TIQ o AME exacto -> ERROR_AMBIGUO_GLOBAL', function () {
  assert.throws(function () { clasificar([GT, GT], [GA], [H], [E]); }, /ERROR_AMBIGUO_GLOBAL/);
  assert.throws(function () { clasificar([GT], [GA, GA], [H], [E]); }, /ERROR_AMBIGUO_GLOBAL/);
});
test('E: historico institucional en Drive existe -> se descarga', function () {
  const r = clasificar([GT], [GA], [H], [null]);
  assert.ok(r.some(function (x) { return x.tipo === 'historico'; }));
  assert.strictEqual(r[0].historico_en_drive, true);
});
test('G: historico inexistente en Drive -> primera ejecucion legitima (no se descarga, flag false)', function () {
  const r = clasificar([GT], [GA], [null], [null]);
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global_tiq', 'global_ame']);
  assert.strictEqual(r[0].historico_en_drive, false);
});
test('H: mas de un historico -> ERROR_AMBIGUO_HISTORICO', function () {
  assert.throws(function () { clasificar([GT], [GA], [H, H], [null]); }, /ERROR_AMBIGUO_HISTORICO/);
});
test('I: estado del periodo existente en Drive -> se descarga (antes de Python)', function () {
  const r = clasificar([GT], [GA], [null], [E]);
  assert.ok(r.some(function (x) { return x.tipo === 'estado' && x.name === E; }));
});
test('K: mas de un estado -> ERROR_AMBIGUO_ESTADO', function () {
  assert.throws(function () { clasificar([GT], [GA], [H], [E, E]); }, /ERROR_AMBIGUO_ESTADO/);
});
test('clasificar: estado de OTRO periodo en la carpeta no se toma', function () {
  const r = clasificar([GT], [GA], [null], ['ESTADO_CONTROL1_INSTITUCIONAL_OCTUBRE_2026.json', null]);
  assert.ok(!r.some(function (x) { return x.tipo === 'estado'; }));
});
test('estado se busca en la carpeta del periodo: si esa busqueda no corrio (periodo nuevo) -> sin estado, sin error', function () {
  const nodos = NODOS_C([GT], [GA], [H], [null]);
  delete nodos['BUSCAR estado del periodo (Drive)'];
  const r = ejecutar(cargar('clasificar'), nodos, []).map(function (i) { return i.json; });
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global_tiq', 'global_ame', 'historico']);
  assert.strictEqual(r[0].estado_en_drive, false);
});
test('el historico que se descarga es SIEMPRE el institucional de la raiz (nombre exacto en 05_CONTROLES), nunca el snapshot de un periodo', function () {
  const c = cargar('clasificar');
  assert.ok(/BUSCAR historico institucional \(Drive\)/.test(c));
  assert.ok(!/snapshot|2026-08|periodo\b.*historico/.test(c.replace(/\/\/.*$/gm, '')));
});
const verificar = function (carpetas) {
  return ejecutar(cargar('verificar_carpeta'), {
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
    'BUSCAR carpeta del periodo (Drive)': carpetas.map(function (n, i) { return { json: n === null ? {} : { id: 'c' + i, name: n } }; }),
  }).map(function (i) { return i.json; })[0];
};
test('carpeta del periodo: 0 -> hay_carpeta=false (periodo nuevo)', function () {
  assert.deepStrictEqual(verificar([null]), { hay_carpeta: false, carpeta_id: null });
  assert.strictEqual(verificar(['2026-08']).hay_carpeta, false); // la de otro periodo no cuenta
});
test('carpeta del periodo: exactamente 1 -> se usa; >1 -> ERROR_AMBIGUO_CARPETA_PERIODO', function () {
  assert.deepStrictEqual(verificar(['2026-08', '2026-09']), { hay_carpeta: true, carpeta_id: 'c1' });
  assert.throws(function () { verificar(['2026-09', '2026-09']); }, /ERROR_AMBIGUO_CARPETA_PERIODO/);
});
test('restaurar/construir_payload usan $(...).first() (no .item) y leen body.anio/mes', function () {
  const w = WH({ anio: 2026, mes: 9, modo: 'official' });
  assert.deepStrictEqual(ejecutar(cargar('restaurar'), w)[0].json, w['WEBHOOK control1'][0].json);
  const p = ejecutar(cargar('construir_payload'), w)[0].json;
  const payload = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.deepStrictEqual([payload.anio, payload.mes], [2026, 9]);
  assert.ok(!/\.item\b/.test(cargar('construir_payload')) && !/\.item\b/.test(cargar('decidir_publicar')));
});
test('construir_payload: nunca incluye `caja` en el payload de Python (CONTROL 1 es institucional)', function () {
  const w = WH({ anio: 2026, mes: 9, caja: 'america' });
  const p = ejecutar(cargar('construir_payload'), w)[0].json;
  const payload = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.ok(!('caja' in payload));
});

const RESULT_BASE = { modo_control1: 'cerrar', estado: 'CERRADO', periodo: 'SEPTIEMBRE_2026', sha_par: 'a'.repeat(64) + '|' + 'b'.repeat(64),
  periodo_cerrado: true, dry_run: false, historico_actualizado: true, filas_incorporadas_historico: 2,
  ruta_detalle_json: RC.dir_entrada + '/' + RC.nombre_detalle };
const decidir = function (r, modo) {
  return ejecutar(cargar('decidir_publicar'), Object.assign(WH({ anio: 2026, mes: 9, modo: modo || 'official' }), { 'RESOLVER control1 (periodo y carpetas)': [{ json: RC }] }), [], { data: r })[0].json;
};
test('cierre con historico actualizado -> detalle + historico + estado se publican; GLOBAL nunca (accion separada)', function () {
  const d = decidir(RESULT_BASE);
  assert.deepStrictEqual([d.debe_publicar, d.hay_detalle, d.hay_historico, d.hay_estado, d.publicar_global], [true, true, true, true, false]);
});
test('PRELIMINAR: aunque el resultado (falso) traiga historico_actualizado, solo se publica el detalle', function () {
  const prelim = Object.assign({}, RESULT_BASE, { modo_control1: 'preliminar', periodo_cerrado: false });
  const d = decidir(prelim);
  assert.deepStrictEqual([d.debe_publicar, d.hay_detalle, d.hay_historico, d.hay_estado, d.publicar_global], [true, true, false, false, false]);
  const sinModo = Object.assign({}, prelim); delete sinModo.modo_control1;
  assert.deepStrictEqual([decidir(sinModo).hay_historico, decidir(sinModo).publicar_global], [false, false]);
});
test('resultado de error / modo dev -> nada se publica', function () {
  assert.strictEqual(decidir({ resultado: 'ERROR', codigo: 'RuntimeError', mensaje: 'x' }).debe_publicar, false);
  assert.strictEqual(decidir({ estado: 'ERROR_TECNICO', problemas: ['GLOBAL_NO_ENCONTRADO'] }).debe_publicar, false);
  assert.strictEqual(decidir(Object.assign({}, RESULT_BASE), 'dev').debe_publicar, false);
});
test('detalle con otro nombre que el del periodo -> no se publica', function () {
  assert.strictEqual(decidir(Object.assign({}, RESULT_BASE, { ruta_detalle_json: RC.dir_entrada + '/CONTROL_ASIGNACIONES_INSTITUCIONAL_OCTUBRE_2026.json' })).hay_detalle, false);
});
test('publicar_global es siempre false: la correccion del GLOBAL viaja en una accion separada', function () {
  [{}, { modo_control1: 'cerrar', historico_actualizado: true }].forEach(function (mut) {
    assert.strictEqual(decidir(Object.assign({}, RESULT_BASE, mut)).publicar_global, false);
  });
});
test('payload: modo preliminar por defecto; cierre solo con modo_control1=cerrar; confirmacion solo si es true', function () {
  const payload = function (body) {
    const p = ejecutar(cargar('construir_payload'), WH(Object.assign({ anio: 2026, mes: 9, modo: 'official' }, body)))[0].json;
    return JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  };
  assert.deepStrictEqual([payload({}).modo_control1, payload({}).confirmacion_cierre], ['preliminar', false]);
  assert.deepStrictEqual([payload({ modo_control1: 'cerrar' }).modo_control1, payload({ modo_control1: 'cerrar' }).confirmacion_cierre], ['cerrar', false]);
  assert.deepStrictEqual([payload({ modo_control1: 'cerrar', confirmacion_cierre: true }).modo_control1, payload({ modo_control1: 'cerrar', confirmacion_cierre: true }).confirmacion_cierre], ['cerrar', true]);
  assert.strictEqual(payload({ modo_control1: 'cerrar', confirmacion_cierre: 'true' }).confirmacion_cierre, false);
});
const CARPETA_PERIODO = 'carpeta-periodo-2026-09';
const lista = function (d) {
  return ejecutar(cargar('lista_publicaciones'), {
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
    'DECIDIR - Publicar CONTROL1 oficial': [{ json: d }],
    'EJECUTAR 07E carpeta del periodo CONTROL1': [{ json: { accion: 'reutilizada', carpeta_id: CARPETA_PERIODO } }],
  }, []).map(function (i) { return i.json; });
};
const ND = 'CONTROL_ASIGNACIONES_INSTITUCIONAL_SEPTIEMBRE_2026.json';
test('publicacion completa: detalle -> estado -> snapshot del historico (periodo) -> historico MAESTRO (raiz) al final; nunca un GLOBAL', function () {
  const l = lista({ hay_detalle: true, hay_estado: true, hay_historico: true, publicar_global: false });
  assert.deepStrictEqual(l.map(function (x) { return x.nombre_archivo; }), [ND, E, H, H]);
  assert.deepStrictEqual(l.map(function (x) { return x.carpeta_id; }),
    [CARPETA_PERIODO, CARPETA_PERIODO, CARPETA_PERIODO, RC.carpeta_controles_id]);
  assert.strictEqual(l[l.length - 1].carpeta_id, RC.carpeta_controles_id); // el maestro de la raiz va ULTIMO
  assert.ok(!l.some(function (x) { return x.nombre_archivo === GT || x.nombre_archivo === GA; }));
  l.forEach(function (x) { assert.strictEqual(x.modo_si_existe, 'actualizar'); assert.ok(x.ruta_local_origen.startsWith(RC.dir_entrada + '/')); assert.ok(!/\/dev_workdir\/global\//.test(x.ruta_local_origen)); });
});
test('publicacion parcial (preliminar): solo detalle; historico maestro NO se toca', function () {
  const l = lista({ hay_detalle: true, hay_estado: false, hay_historico: false, publicar_global: false });
  assert.deepStrictEqual(l.map(function (x) { return x.nombre_archivo; }), [ND]);
  assert.ok(!l.some(function (x) { return x.carpeta_id === RC.carpeta_controles_id; }));
});
test('sin carpeta de periodo resuelta por 07E -> error explicito (no se publica a otro sitio)', function () {
  assert.throws(function () {
    ejecutar(cargar('lista_publicaciones'), {
      'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
      'DECIDIR - Publicar CONTROL1 oficial': [{ json: { hay_detalle: true } }],
      'EJECUTAR 07E carpeta del periodo CONTROL1': [{ json: {} }],
    }, []);
  }, /CARPETA_PERIODO_CONTROL1_NO_RESUELTA/);
});
test('ningun nodo nuevo referencia dev_workdir/global/ ni publicacion/ como fuente', function () {
  ['resolver', 'clasificar', 'verificar_carpeta', 'restaurar', 'construir_payload', 'decidir_publicar', 'lista_publicaciones'].forEach(function (n) {
    assert.ok(!/dev_workdir\/global\/|publicacion\//.test(cargar(n)), n);
  });
});
test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8')); const nodos = (wf.workflow || wf).nodes;
  const mapa = { 'RESOLVER control1 (periodo y carpetas)': 'resolver', 'CLASIFICAR - Artefactos de CONTROL 1 en Drive': 'clasificar',
    'RESTAURAR - Item del webhook control1': 'restaurar', 'CONSTRUIR payload control1': 'construir_payload',
    'DECIDIR - Publicar CONTROL1 oficial': 'decidir_publicar', 'CONSTRUIR - Lista publicaciones CONTROL1': 'lista_publicaciones',
    'VERIFICAR carpeta del periodo (CONTROL1)': 'verificar_carpeta' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    assert.ok(nodo, 'falta nodo ' + nombre);
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), 'desalineado: ' + nombre);
  });
});
console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

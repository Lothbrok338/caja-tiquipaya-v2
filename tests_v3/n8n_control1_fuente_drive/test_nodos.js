/**
 * tests_v3/n8n_control1_fuente_drive/test_nodos.js -- FASE 12E.4.
 *
 * Ejecuta, con Node puro (sin n8n ni Drive), el codigo REAL de los nodos Code que
 * materializan las entradas de CONTROL 1 desde Drive y deciden que se publica, y
 * verifica que ese mismo texto es el desplegado en el snapshot de BACKEND DEV.
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
const NODOS_C = function (g, h, r) {
  return {
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
    'BUSCAR GLOBAL oficial (Drive)': g.map(function (n, i) { return { json: n === null ? {} : { id: 'g' + i, name: n } }; }),
    'BUSCAR historico asignaciones (Drive)': h.map(function (n, i) { return { json: n === null ? {} : { id: 'h' + i, name: n } }; }),
    'BUSCAR revision del periodo (Drive)': r.map(function (n, i) { return { json: n === null ? {} : { id: 'r' + i, name: n } }; }),
  };
};
const G = 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx', H = 'HISTORICO_ASIGNACIONES.csv', R = 'REVISION_ASIGNACIONES_SEPTIEMBRE_2026.xlsx';
const clasificar = function (g, h, r) { return ejecutar(cargar('clasificar'), NODOS_C(g, h, r), []).map(function (i) { return i.json; }); };

test('resolver: septiembre 2026 -> nombres, dir aislado control1_entrada/2026-09 y carpetas de Drive', function () {
  assert.strictEqual(RC.periodo, '2026-09');
  assert.strictEqual(RC.nombre_global, G);
  assert.strictEqual(RC.nombre_historico, H);
  assert.strictEqual(RC.nombre_revision, R);
  assert.strictEqual(RC.nombre_detalle, 'CONTROL_ASIGNACIONES_SEPTIEMBRE_2026.json');
  assert.ok(RC.dir_entrada.endsWith('/dev_workdir/control1_entrada/2026-09'));
  assert.ok(!/\/global\/|publicacion/.test(RC.dir_entrada));
  assert.strictEqual(RC.carpeta_global_id, '1KREzDpgptWRwuArA1qYco49rplOEeeNU');
  assert.strictEqual(RC.carpeta_controles_id, '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB');
  assert.strictEqual(RC.carpeta_control1_id, '1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk');
});
test('resolver: los 12 meses generan el nombre canonico (mismo que consolidador_mensual)', function () {
  const esperados = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'];
  esperados.forEach(function (m, i) {
    const r = ejecutar(cargar('resolver'), WH({ anio: 2027, mes: i + 1 }))[0].json;
    assert.strictEqual(r.nombre_global, 'SAP_GLOBAL_TIQ_' + m + '_2027.xlsx');
    assert.strictEqual(r.nombre_revision, 'REVISION_ASIGNACIONES_' + m + '_2027.xlsx');
  });
});
test('resolver: anio/mes invalidos fallan', function () {
  [['2026', 9], [2026, 13], [2026, 0], [1999, 9], [undefined, 9], [2026, 9.5]].forEach(function (p) {
    assert.throws(function () { ejecutar(cargar('resolver'), WH({ anio: p[0], mes: p[1] })); }, /PERIODO_INVALIDO/);
  });
});
// FASE 12F -- aislamiento por CAJA: mismo patron (env DRIVE_*_TIQ/AME, fail
// cerrado para AMERICA) que config_drive_oficial.py.
test('resolver: caja ausente -> default tiquipaya (rutas y nombre historicos intactos, sin /america/)', function () {
  assert.strictEqual(RC.caja, 'tiquipaya');
  assert.strictEqual(RC.nombre_global, 'SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx');
  assert.ok(!RC.dir_entrada.includes('/america/'));
});
test('resolver: caja="america" sin variables DRIVE_*_AME -> falla cerrado (DRIVE_AME_PENDIENTE), nunca hereda IDs de TIQ', function () {
  assert.throws(function () { ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, caja: 'america' })); }, /DRIVE_AME_PENDIENTE/);
});
test('resolver: caja="america" con las 3 variables -> nombre SAP_GLOBAL_AME_, dir bajo /america/, IDs distintos de TIQ', function () {
  const env = { DRIVE_CONTROLES_AME: 'ame-controles-1', DRIVE_GLOBAL_AME: 'ame-global-1', DRIVE_CONTROL1_AME: 'ame-control1-1' };
  const r = ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, caja: 'america' }), [], undefined, env)[0].json;
  assert.strictEqual(r.caja, 'america');
  assert.strictEqual(r.nombre_global, 'SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx');
  assert.strictEqual(r.carpeta_controles_id, 'ame-controles-1');
  assert.strictEqual(r.carpeta_global_id, 'ame-global-1');
  assert.strictEqual(r.carpeta_control1_id, 'ame-control1-1');
  assert.ok(r.dir_entrada.endsWith('/dev_workdir/control1_entrada/america/2026-09'));
  [r.carpeta_controles_id, r.carpeta_global_id, r.carpeta_control1_id].forEach(function (id) {
    assert.notStrictEqual(id, RC.carpeta_controles_id);
    assert.notStrictEqual(id, RC.carpeta_global_id);
    assert.notStrictEqual(id, RC.carpeta_control1_id);
  });
});
test('resolver: caja invalida falla cerrado con CAJA_DESCONOCIDA', function () {
  assert.throws(function () { ejecutar(cargar('resolver'), WH({ anio: 2026, mes: 9, caja: 'brasil' })); }, /CAJA_DESCONOCIDA/);
});
test('A: GLOBAL oficial existe (con historico y revision) -> los 3 se descargan a control1_entrada', function () {
  const r = clasificar([G], [H], [R]);
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global', 'historico', 'revision']);
  r.forEach(function (x) { assert.ok(x.ruta_destino.startsWith(RC.dir_entrada + '/')); });
  assert.strictEqual(r[0].id, 'g0');
});
test('B: nombres parecidos/no exactos en la carpeta GLOBAL se ignoran (solo el exacto cuenta)', function () {
  const r = clasificar(['SAP_GLOBAL_TIQ_SEPTIEMBRE_2026_copia.xlsx', G, 'SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx'], [H], [null]);
  assert.strictEqual(r.filter(function (x) { return x.tipo === 'global'; }).length, 1);
  assert.strictEqual(r.find(function (x) { return x.tipo === 'global'; }).name, G);
});
test('C: GLOBAL oficial inexistente (busqueda vacia {}) -> GLOBAL_OFICIAL_NO_ENCONTRADO', function () {
  assert.throws(function () { clasificar([null], [H], [R]); }, /GLOBAL_OFICIAL_NO_ENCONTRADO/);
});
test('D: mas de un GLOBAL exacto -> ERROR_AMBIGUO_GLOBAL', function () {
  assert.throws(function () { clasificar([G, G], [H], [R]); }, /ERROR_AMBIGUO_GLOBAL/);
});
test('E: historico en Drive existe -> se descarga', function () {
  const r = clasificar([G], [H], [null]);
  assert.ok(r.some(function (x) { return x.tipo === 'historico'; }));
  assert.strictEqual(r[0].historico_en_drive, true);
});
test('G: historico inexistente en Drive -> primera ejecucion legitima (no se descarga, flag false)', function () {
  const r = clasificar([G], [null], [null]);
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global']);
  assert.strictEqual(r[0].historico_en_drive, false);
});
test('H: mas de un historico -> ERROR_AMBIGUO_HISTORICO', function () {
  assert.throws(function () { clasificar([G], [H, H], [null]); }, /ERROR_AMBIGUO_HISTORICO/);
});
test('I: revision existente en Drive -> se descarga (antes de Python)', function () {
  const r = clasificar([G], [null], [R]);
  assert.ok(r.some(function (x) { return x.tipo === 'revision' && x.name === R; }));
});
test('K: mas de una revision -> ERROR_AMBIGUO_REVISION', function () {
  assert.throws(function () { clasificar([G], [H], [R, R]); }, /ERROR_AMBIGUO_REVISION/);
});
test('clasificar: revision de OTRO periodo en la carpeta no se toma', function () {
  const r = clasificar([G], [null], ['REVISION_ASIGNACIONES_OCTUBRE_2026.xlsx', null]);
  assert.ok(!r.some(function (x) { return x.tipo === 'revision'; }));
});
test('revision se busca en la carpeta del periodo: si esa busqueda no corrio (periodo nuevo) -> sin revision, sin error', function () {
  const nodos = NODOS_C([G], [H], [null]);
  delete nodos['BUSCAR revision del periodo (Drive)'];
  const r = ejecutar(cargar('clasificar'), nodos, []).map(function (i) { return i.json; });
  assert.deepStrictEqual(r.map(function (x) { return x.tipo; }), ['global', 'historico']);
  assert.strictEqual(r[0].revision_en_drive, false);
});
test('el historico que se descarga es SIEMPRE el de la raiz (nombre exacto en 05_CONTROLES), nunca el snapshot de un periodo', function () {
  const c = cargar('clasificar');
  assert.ok(/BUSCAR historico asignaciones \(Drive\)/.test(c));
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

const RESULT_BASE = { modo_control1: 'cerrar', estado: 'REVISAR_DUPLICADOS_ENCONTRADOS', estado_validacion: 'PENDIENTE_VALIDACION_AUDITOR', archivo_global: G, periodo: 'SEPTIEMBRE_2026',
  global_modificado: false, correcciones_aplicadas: 0, dry_run: false, historico_actualizado: false, revision_actualizada: true,
  ruta_revision: RC.dir_entrada + '/' + R, detalle_json: RC.dir_entrada + '/' + RC.nombre_detalle, sha256_global_original: 'a'.repeat(64), sha256_global_final: 'a'.repeat(64) };
const decidir = function (r, modo) {
  return ejecutar(cargar('decidir_publicar'), Object.assign(WH({ anio: 2026, mes: 9, modo: modo || 'official' }), { 'RESOLVER control1 (periodo y carpetas)': [{ json: RC }] }), [], { data: r })[0].json;
};
test('M/N: alertas pendientes -> solo revision se publica; historico NO; GLOBAL NO', function () {
  const d = decidir(RESULT_BASE);
  assert.deepStrictEqual([d.debe_publicar, d.hay_revision, d.hay_detalle, d.hay_historico, d.publicar_global], [true, true, true, false, false]);
});
test('sin alertas (OK_SIN_DUPLICADOS): solo historico', function () {
  const d = decidir(Object.assign({}, RESULT_BASE, { estado: 'OK_SIN_DUPLICADOS', estado_validacion: null, revision_actualizada: false, ruta_revision: null, historico_actualizado: true }));
  assert.deepStrictEqual([d.hay_revision, d.hay_historico, d.publicar_global], [false, true, false]);
});
test('correccion autorizada y aplicada -> GLOBAL corregido + revision + historico', function () {
  const d = decidir(Object.assign({}, RESULT_BASE, { estado_validacion: 'CERRADO_CON_VALIDACION_AUDITOR', global_modificado: true, correcciones_aplicadas: 2, historico_actualizado: true, sha256_global_final: 'b'.repeat(64) }));
  assert.deepStrictEqual([d.publicar_global, d.hay_revision, d.hay_historico], [true, true, true]);
});
test('GLOBAL NO se publica si: sin cerrar, sin cambio de SHA, dry_run, otro periodo/archivo, sin correcciones', function () {
  const ok = Object.assign({}, RESULT_BASE, { estado_validacion: 'CERRADO_CON_VALIDACION_AUDITOR', global_modificado: true, correcciones_aplicadas: 1, sha256_global_final: 'b'.repeat(64) });
  assert.strictEqual(decidir(ok).publicar_global, true);
  [{ estado_validacion: 'PENDIENTE_VALIDACION_AUDITOR' }, { sha256_global_final: 'a'.repeat(64) }, { dry_run: true }, { periodo: 'OCTUBRE_2026' },
   { archivo_global: 'SAP_GLOBAL_TIQ_OCTUBRE_2026.xlsx' }, { correcciones_aplicadas: 0 }, { global_modificado: false }, { sha256_global_original: undefined }].forEach(function (mut) {
    assert.strictEqual(decidir(Object.assign({}, ok, mut)).publicar_global, false, JSON.stringify(mut));
  });
});
test('PRELIMINAR: aunque el resultado (falso) traiga historico/GLOBAL modificados, solo se publican revision y detalle', function () {
  const prelim = Object.assign({}, RESULT_BASE, { modo_control1: 'preliminar', estado_control1: 'PRELIMINAR_LISTO_PARA_CERRAR', historico_actualizado: true,
    global_modificado: true, correcciones_aplicadas: 2, estado_validacion: 'CERRADO_CON_VALIDACION_AUDITOR', sha256_global_final: 'b'.repeat(64) });
  const d = decidir(prelim);
  assert.deepStrictEqual([d.debe_publicar, d.hay_revision, d.hay_detalle, d.hay_historico, d.publicar_global], [true, true, true, false, false]);
  const sinModo = Object.assign({}, prelim); delete sinModo.modo_control1;
  assert.deepStrictEqual([decidir(sinModo).hay_historico, decidir(sinModo).publicar_global], [false, false]);
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
test('construir_payload: propaga caja al payload de Python (default tiquipaya; america si el webhook la trae)', function () {
  const payload = function (body) {
    const p = ejecutar(cargar('construir_payload'), WH(Object.assign({ anio: 2026, mes: 9, modo: 'official' }, body)))[0].json;
    return JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  };
  assert.strictEqual(payload({}).caja, 'tiquipaya');
  assert.strictEqual(payload({ caja: 'america' }).caja, 'america');
});
test('resultado de error / modo dev -> nada se publica', function () {
  assert.strictEqual(decidir({ resultado: 'ERROR', codigo: 'RuntimeError', mensaje: 'x' }).debe_publicar, false);
  assert.strictEqual(decidir({ estado: 'ERROR_TECNICO', problemas: ['GLOBAL_NO_ENCONTRADO'] }).debe_publicar, false);
  assert.strictEqual(decidir(Object.assign({}, RESULT_BASE, { historico_actualizado: true }), 'dev').debe_publicar, false);
});
test('revision con otro nombre que el del periodo -> no se publica', function () {
  assert.strictEqual(decidir(Object.assign({}, RESULT_BASE, { ruta_revision: RC.dir_entrada + '/REVISION_ASIGNACIONES_OCTUBRE_2026.xlsx' })).hay_revision, false);
});
const CARPETA_PERIODO = 'carpeta-periodo-2026-09';
const lista = function (d) {
  return ejecutar(cargar('lista_publicaciones'), {
    'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
    'DECIDIR - Publicar CONTROL1 oficial': [{ json: d }],
    'EJECUTAR 07E carpeta del periodo CONTROL1': [{ json: { accion: 'reutilizada', carpeta_id: CARPETA_PERIODO } }],
  }, []).map(function (i) { return i.json; });
};
const ND = 'CONTROL_ASIGNACIONES_SEPTIEMBRE_2026.json';
test('publicacion completa: GLOBAL -> revision -> detalle -> snapshot del historico (periodo) -> historico MAESTRO (raiz) al final', function () {
  const l = lista({ publicar_global: true, hay_revision: true, hay_detalle: true, hay_historico: true });
  assert.deepStrictEqual(l.map(function (x) { return x.nombre_archivo; }), [G, R, ND, H, H]);
  assert.deepStrictEqual(l.map(function (x) { return x.carpeta_id; }),
    [RC.carpeta_global_id, CARPETA_PERIODO, CARPETA_PERIODO, CARPETA_PERIODO, RC.carpeta_controles_id]);
  assert.strictEqual(l[l.length - 1].carpeta_id, RC.carpeta_controles_id); // el maestro de la raiz va ULTIMO
  l.forEach(function (x) { assert.strictEqual(x.modo_si_existe, 'actualizar'); assert.ok(x.ruta_local_origen.startsWith(RC.dir_entrada + '/')); assert.ok(!/\/dev_workdir\/global\//.test(x.ruta_local_origen)); });
});
test('la revision de septiembre NUNCA va suelta a la raiz de CONTROL_1_ASIGNACIONES: siempre a la carpeta del periodo', function () {
  const l = lista({ publicar_global: false, hay_revision: true, hay_detalle: true, hay_historico: true });
  l.forEach(function (x) { assert.notStrictEqual(x.carpeta_id, RC.carpeta_control1_id); });
  assert.ok(l.filter(function (x) { return x.nombre_archivo === R; }).every(function (x) { return x.carpeta_id === CARPETA_PERIODO; }));
});
test('publicacion parcial: alertas pendientes -> revision + detalle en el periodo; historico maestro NO se toca', function () {
  const l = lista({ publicar_global: false, hay_revision: true, hay_detalle: true, hay_historico: false });
  assert.deepStrictEqual(l.map(function (x) { return x.nombre_archivo; }), [R, ND]);
  assert.ok(!l.some(function (x) { return x.carpeta_id === RC.carpeta_controles_id; }));
});
test('sin carpeta de periodo resuelta por 07E -> error explicito (no se publica a otro sitio)', function () {
  assert.throws(function () {
    ejecutar(cargar('lista_publicaciones'), {
      'RESOLVER control1 (periodo y carpetas)': [{ json: RC }],
      'DECIDIR - Publicar CONTROL1 oficial': [{ json: { hay_revision: true } }],
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

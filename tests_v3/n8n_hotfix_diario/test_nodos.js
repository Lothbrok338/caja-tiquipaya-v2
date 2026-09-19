/**
 * tests_v3/n8n_hotfix_diario/test_nodos.js -- HOTFIX 2026-09-19.
 * Ejecuta con Node puro el codigo REAL de los nodos Code nuevos/modificados de /procesar (MACROS y cierre desde Drive)
 * y /publicar (estado oficial) y verifica que ese texto es el desplegado en el snapshot de BACKEND DEV.
 * Uso: node tests_v3/n8n_hotfix_diario/test_nodos.js
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
    return { first: function () { return items[0]; }, all: function () { return items; }, item: items[0] };
  };
  const $input = { all: function () { return entradas || []; }, first: function () { return (entradas || [])[0]; } };
  return new Function('$', '$input', '$json', '$execution', 'Buffer', codigo)($, $input, json || {}, { id: 'test-1' }, Buffer);
}
let pasados = 0, fallidos = 0;
function test(nombre, fn) { try { fn(); pasados++; console.log('PASS - ' + nombre); } catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); } }

const LOTE = 'abc123def456';
const base = function (fechaInicio) {
  return {
    'INTERPRETAR resultado crear_lote_pendiente': [{ json: { data: { lote_id: LOTE } } }],
    'WEBHOOK procesar': [{ json: { body: { fecha_inicio: fechaInicio || '2026-09-12', fecha_fin: '2026-09-12' } } }],
  };
};
const RP = ejecutar(cargar('resolver_procesar'), base())[0].json;
const ING = function (cierres) { return { 'EJECUTAR - 01 INGESTA (Drive real)': [{ json: { data: { cierres: cierres } } }] }; };
const clasif = function (macros, cierres, rp) {
  const nodos = Object.assign({ 'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: rp || RP }],
    'BUSCAR MACROS oficial (Drive)': macros.map(function (n, i) { return { json: n === null ? {} : { id: 'm' + i, name: n } }; }) }, ING(cierres));
  return ejecutar(cargar('clasificar_procesar'), nodos, []).map(function (i) { return i.json; });
};
const ENC = function (fecha, id) { return { fecha: fecha, estado_ingesta: 'ENCONTRADO', drive_file_id: id, archivo_esperado: 'CIERRE ' + fecha.slice(8) + '-' + fecha.slice(5, 7) + '-' + fecha.slice(0, 4) + '.xlsm' }; };

test('resolver: MACROS oficial de septiembre por nombre exacto + carpeta; entrada aislada por lote', function () {
  assert.strictEqual(RP.macros_nombre, 'MACROS SEPTIEMBRE.xlsm');
  assert.strictEqual(RP.macros_carpeta_id, '1U0HBoAsiDZy8Dqr3zEHa8_YfS5XcoMab');
  assert.ok(RP.dir_entrada.endsWith('/dev_workdir/procesar_entrada/' + LOTE));
  assert.strictEqual(RP.dir_cierres, RP.dir_entrada + '/cierres');
  assert.ok(!/maestro_origen|cierres_origen|publicacion\//.test(RP.dir_entrada));
  assert.strictEqual(RP.macros_configurado, true);
});
test('resolver: periodo sin MACROS configurado -> macros_configurado=false (falla explicito, sin copia local)', function () {
  const r = ejecutar(cargar('resolver_procesar'), base('2026-10-01'))[0].json;
  assert.strictEqual(r.macros_configurado, false);
  const c = clasif([], [], r);
  assert.strictEqual(c[0].hay_error, true); assert.match(c[0].mensaje_error, /MACROS_OFICIAL_NO_CONFIGURADO/);
});
test('clasificar: MACROS unico + cierres ENCONTRADOS -> descargas con su id exacto y ruta en procesar_entrada', function () {
  const c = clasif(['MACROS SEPTIEMBRE.xlsm'], [ENC('2026-09-11', 'F11'), ENC('2026-09-12', 'F12'), { fecha: '2026-09-13', estado_ingesta: 'SIN_ARCHIVO' }]);
  assert.deepStrictEqual(c.map(function (i) { return i.tipo + ':' + i.id; }), ['macros:m0', 'cierre:F11', 'cierre:F12']);
  c.forEach(function (i) { assert.strictEqual(i.hay_error, false); assert.ok(i.ruta_destino.indexOf(RP.dir_entrada) === 0); });
  assert.strictEqual(c[0].ruta_destino, RP.dir_entrada + '/MACROS SEPTIEMBRE.xlsm');
  assert.strictEqual(c[2].ruta_destino, RP.dir_cierres + '/CIERRE 12-09-2026.xlsm');
});
test('clasificar: 0 MACROS -> MACROS_OFICIAL_NO_ENCONTRADO; >1 -> ERROR_AMBIGUO_MACROS (nunca elige uno)', function () {
  assert.match(clasif([null], [ENC('2026-09-12', 'F')])[0].mensaje_error, /MACROS_OFICIAL_NO_ENCONTRADO/);
  assert.match(clasif(['OTRO.xlsm'], [ENC('2026-09-12', 'F')])[0].mensaje_error, /MACROS_OFICIAL_NO_ENCONTRADO/);
  const amb = clasif(['MACROS SEPTIEMBRE.xlsm', 'MACROS SEPTIEMBRE.xlsm'], [ENC('2026-09-12', 'F')]);
  assert.strictEqual(amb.length, 1); assert.match(amb[0].mensaje_error, /ERROR_AMBIGUO_MACROS/);
});
test('clasificar: solo MACROS si ningun cierre fue ENCONTRADO; sin duplicar el mismo drive_file_id', function () {
  assert.strictEqual(clasif(['MACROS SEPTIEMBRE.xlsm'], [{ fecha: '2026-09-13', estado_ingesta: 'SIN_ARCHIVO' }]).length, 1);
  assert.strictEqual(clasif(['MACROS SEPTIEMBRE.xlsm'], [ENC('2026-09-12', 'F'), ENC('2026-09-12', 'F')]).length, 2);
});
test('payload procesar_lote: origen del cierre y de MACROS = procesar_entrada del lote (nunca las copias estaticas)', function () {
  const nodos = Object.assign(base(), { 'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: RP }] });
  const p = ejecutar(cargar('construir_payload_procesar_lote'), nodos, [{ json: { data: { cierres: [ENC('2026-09-12', 'F')] } } }])[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(pl.origen_cierres_dir, RP.dir_cierres);
  assert.strictEqual(pl.ruta_maestro_origen, RP.dir_entrada + '/MACROS SEPTIEMBRE.xlsm');
  assert.ok(!/maestro_origen\/|cierres_origen/.test(JSON.stringify([pl.origen_cierres_dir, pl.ruta_maestro_origen])));
  assert.strictEqual(pl.requiere_ingesta_drive, true); assert.strictEqual(pl.lote_id, LOTE);
  assert.ok(pl.ingesta_precomputada.length === 1);
  assert.ok(!/\.item\b/.test(cargar('construir_payload_procesar_lote')));
});
test('marcar_lote_error: el mensaje funcional llega al lote', function () {
  const nodos = { 'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: RP }], 'CLASIFICAR - MACROS y cierres de procesar': [{ json: { hay_error: true, mensaje_error: 'ERROR_AMBIGUO_MACROS: x' } }] };
  const p = ejecutar(cargar('construir_payload_marcar_error'), nodos, [])[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.deepStrictEqual([pl.lote_id, pl.mensaje], [LOTE, 'ERROR_AMBIGUO_MACROS: x']);
});
test('restaurar_procesar: devuelve la salida de la ingesta', function () {
  const n = ING([ENC('2026-09-12', 'F')]);
  assert.deepStrictEqual(ejecutar(cargar('restaurar_procesar'), n, [])[0].json, n['EJECUTAR - 01 INGESTA (Drive real)'][0].json);
});
test('publicar: el payload pide modo_oficial=true (el paso local solo prepara)', function () {
  const p = ejecutar(cargar('construir_payload_publicar'), {}, [{ json: { body: { lote_id: LOTE, fechas: ['2026-09-11'], usuario_auditor: 'G' } } }])[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(pl.modo_oficial, true); assert.deepStrictEqual(pl.fechas, ['2026-09-11']);
});
test('consolidar: envia respuesta + lote_id a Python; el nodo no decide el estado', function () {
  const resp = { resultado: 'OK', publicados: [{ fecha: '2026-09-11' }], publicados_drive_oficial: [] };
  const p = ejecutar(cargar('construir_payload_consolidar'), { 'WEBHOOK publicar': [{ json: { body: { lote_id: LOTE } } }] }, [], resp)[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.deepStrictEqual([pl.lote_id, pl.respuesta], [LOTE, resp]);
  assert.ok(!/PUBLICADO_OFICIAL|estado_publicacion/.test(cargar('construir_payload_consolidar').replace(/\/\/.*$/gm, '')));
});
test('respuesta final: parsea la salida de Python; sin salida -> ERROR (nunca un PUBLICADO por omision)', function () {
  const ok = { resultado: 'OK', publicados: [{ estado_publicacion: 'ERROR_PUBLICACION_OFICIAL' }] };
  assert.deepStrictEqual(ejecutar(cargar('respuesta_publicar_final'), {}, [{ json: { stdout: JSON.stringify(ok) } }])[0].json, ok);
  const e = ejecutar(cargar('respuesta_publicar_final'), {}, [{ json: { stdout: '', stderr: 'boom' } }])[0].json;
  assert.strictEqual(e.resultado, 'ERROR'); assert.match(e.mensaje, /boom/);
});
test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  if (!fs.existsSync(snapshot)) { console.log('       (snapshot ausente: omitido)'); return; }
  const wf = JSON.parse(fs.readFileSync(snapshot, 'utf8')); const nodos = (wf.workflow || wf).nodes;
  const mapa = { 'RESOLVER procesar_entrada (MACROS y cierres)': 'resolver_procesar', 'CLASIFICAR - MACROS y cierres de procesar': 'clasificar_procesar',
    'RESTAURAR - Ingesta para procesar': 'restaurar_procesar', 'CONSTRUIR payload marcar_lote_error': 'construir_payload_marcar_error',
    'CONSTRUIR payload procesar_lote': 'construir_payload_procesar_lote', 'CONSTRUIR payload publicar': 'construir_payload_publicar',
    'CONSTRUIR payload consolidar publicar': 'construir_payload_consolidar', 'RESPUESTA publicar (estado oficial)': 'respuesta_publicar_final' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    if (!nodo) assert.fail('falta nodo ' + nombre);
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), nombre);
  });
  const C = (wf.workflow || wf).connections;
  const sig = function (n, i) { return ((C[n] || {}).main || [])[i || 0].map(function (t) { return t.node; }); };
  assert.deepStrictEqual(sig('EJECUTAR - 01 INGESTA (Drive real)'), ['RESOLVER procesar_entrada (MACROS y cierres)']);
  assert.deepStrictEqual(sig('RESTAURAR - Ingesta para procesar'), ['CONSTRUIR payload procesar_lote']);
  assert.deepStrictEqual(sig('CONSTRUIR - Respuesta sin Drive oficial'), ['CONSTRUIR payload consolidar publicar']);
  assert.deepStrictEqual(sig('COMBINAR - Resultado local + Drive oficial'), ['CONSTRUIR payload consolidar publicar']);
  assert.deepStrictEqual(sig('RESPUESTA publicar (estado oficial)'), ['RESPONDER publicar']);
});
console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

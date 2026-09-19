/**
 * tests_v3/n8n_shadow_guard/test_nodos.js -- migración Railway 2026-09.
 * Ejecuta con Node puro el código REAL (extraído directamente de
 * snapshots/railway-shadow/, no de una copia mantenida a mano — cero
 * riesgo de que este test y el generador diverjan) de:
 *   - la guarda SHADOW insertada en 06B/07D/07E (bloquea antes de
 *     cualquier nodo Google Drive de escritura);
 *   - los 6 nodos de BACKEND parcheados para que publication_mode,
 *     modo_oficial y las decisiones de publicar GLOBAL/CONTROL1/CONTROL3
 *     se deriven de TIQ_BLOCK_OFFICIAL_PUBLISH.
 * No ejecuta nada contra Drive/n8n real: todo corre en memoria, con
 * $env/$input/$json/$('Nodo') mockeados.
 * Uso: node tests_v3/n8n_shadow_guard/test_nodos.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', '..', 'snapshots', 'railway-shadow');
const cargarWorkflow = function (nombre) { return JSON.parse(fs.readFileSync(path.join(DIR, nombre), 'utf8')); };
const nodoPorNombre = function (wf, nombre) {
  const n = wf.nodes.find(function (x) { return x.name === nombre; });
  if (!n) throw new Error('nodo no encontrado: ' + nombre);
  return n;
};

function ejecutar(codigo, opts) {
  opts = opts || {};
  const nodos = opts.nodos || {};
  const $ = function (nombre) {
    if (!(nombre in nodos)) throw new Error('nodo no mockeado: ' + nombre);
    const items = nodos[nombre];
    return { first: function () { return items[0]; }, all: function () { return items; }, item: items[0] };
  };
  const entradas = opts.entradas || [{ json: {} }];
  const $input = { all: function () { return entradas; }, first: function () { return entradas[0]; } };
  const $env = opts.env || {};
  return new Function('$', '$input', '$json', '$execution', 'Buffer', '$env', codigo)(
    $, $input, opts.json || {}, { id: 'test-1' }, Buffer, $env
  );
}

let pasados = 0, fallidos = 0;
function test(nombre, fn) { try { fn(); pasados++; console.log('PASS - ' + nombre); } catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); } }

// ---------------------------------------------------------------------
// A) Guarda de escritura en 06B / 07D / 07E
// ---------------------------------------------------------------------
const SUBWORKFLOWS_CON_GUARDA = [
  ['wcgxNei3duWfMDp1_06b_publicacion_oficial.json', 'BUSCAR - Marker existente en Drive'],
  ['HhuQCVP2oCubavzY_07d_publicar_oficial.json', 'BUSCAR - Archivo por nombre en carpeta'],
  ['Lht5xRinJ9nJpHCW_07e_buscar_crear_carpeta.json', 'BUSCAR - Subcarpeta por nombre'],
];
const NOMBRE_GUARDIA = 'GUARDIA SHADOW (bloquea si TIQ_BLOCK_OFFICIAL_PUBLISH)';

SUBWORKFLOWS_CON_GUARDA.forEach(function (par) {
  const archivo = par[0], destinoOriginal = par[1];
  const wf = cargarWorkflow(archivo);
  const trigger = nodoPorNombre(wf, 'ENTRADA (Execute Workflow Trigger)');
  const guardia = nodoPorNombre(wf, NOMBRE_GUARDIA);
  const codigo = guardia.parameters.jsCode;

  test(archivo + ': trigger está cableado hacia la guardia (no directo al primer BUSCAR)', function () {
    assert.strictEqual(wf.connections[trigger.name].main[0][0].node, NOMBRE_GUARDIA);
  });
  test(archivo + ': la guardia reapunta exactamente al destino original del trigger', function () {
    assert.strictEqual(wf.connections[NOMBRE_GUARDIA].main[0][0].node, destinoOriginal);
  });
  test(archivo + ': con TIQ_BLOCK_OFFICIAL_PUBLISH=true la guardia lanza ANTES de cualquier Drive', function () {
    assert.throws(function () { ejecutar(codigo, { env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } }); }, /PUBLICACION_OFICIAL_BLOQUEADA_POR_ENTORNO/);
  });
  ['1', 'yes', 'TRUE', 'Yes'].forEach(function (v) {
    test(archivo + ': también bloquea con TIQ_BLOCK_OFFICIAL_PUBLISH=' + v, function () {
      assert.throws(function () { ejecutar(codigo, { env: { TIQ_BLOCK_OFFICIAL_PUBLISH: v } }); }, /PUBLICACION_OFICIAL_BLOQUEADA_POR_ENTORNO/);
    });
  });
  test(archivo + ': sin la variable (o en false) la guardia deja pasar el item tal cual', function () {
    const item = { json: { x: 1 } };
    assert.deepStrictEqual(ejecutar(codigo, { entradas: [item] }), [item]);
    assert.deepStrictEqual(ejecutar(codigo, { entradas: [item], env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'false' } }), [item]);
  });
});

// ---------------------------------------------------------------------
// B) BACKEND — publication_mode / modo_oficial / hay_elegibles / debe_publicar
// ---------------------------------------------------------------------
const BACKEND = cargarWorkflow('aLs1f3GMqswbaENA_backend_dev.json');
const codigoDe = function (nombre) { return nodoPorNombre(BACKEND, nombre).parameters.jsCode; };

test('BACKEND expone publication_mode=dev con SHADOW=true (y "official" sin la variable)', function () {
  const codigo = codigoDe('AGREGAR - publication_mode');
  const conGuard = ejecutar(codigo, { json: { data: { lote_id: 'L1' } }, env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } })[0].json;
  assert.strictEqual(conGuard.publication_mode, 'dev');
  assert.strictEqual(conGuard.lote_id, 'L1'); // el resto del payload se preserva
  const sinGuard = ejecutar(codigo, { json: { data: {} } })[0].json;
  assert.strictEqual(sinGuard.publication_mode, 'official');
});

test('BACKEND: modo_oficial en el payload de /publicar se deriva del guard', function () {
  const codigo = codigoDe('CONSTRUIR payload publicar');
  const entradas = [{ json: { body: { lote_id: 'L1', fechas: ['2026-09-11'], usuario_auditor: 'X' } } }];
  const leer = function (env) {
    const salida = ejecutar(codigo, { entradas: entradas, env: env })[0].json;
    return JSON.parse(Buffer.from(salida.input_b64, 'base64').toString('utf8'));
  };
  assert.strictEqual(leer({ TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' }).modo_oficial, false);
  assert.strictEqual(leer({}).modo_oficial, true);
});

test('BACKEND no deriva a 06B: hay_elegibles=false con SHADOW=true aunque Python haya devuelto publicados válidos', function () {
  const codigo = codigoDe('PREPARAR - Cierres elegibles para Drive oficial');
  const publicadosValidos = { data: { publicados: [{ ruta_sap_publicado: 'a', ruta_resultado_publicado: 'b', ruta_marker: 'c', sha256: 'd' }] } };
  const conGuard = ejecutar(codigo, { json: publicadosValidos, env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } })[0].json;
  assert.deepStrictEqual(conGuard, { elegibles: [], hay_elegibles: false });
  const sinGuard = ejecutar(codigo, { json: publicadosValidos })[0].json;
  assert.strictEqual(sinGuard.hay_elegibles, true);
});

test('BACKEND no deriva a 07D/07E vía GLOBAL: debe_publicar=false con SHADOW=true aunque modo=official y estado listo', function () {
  const codigo = codigoDe('DECIDIR - Publicar GLOBAL oficial');
  const nodos = { 'WEBHOOK global': [{ json: { body: { modo: 'official' } } }] };
  const json = { data: { estado: 'VALIDADO_PENDIENTE_PUBLICACION', ruta_global_generado: 'g', ruta_resultado_json: 'r' } };
  assert.strictEqual(ejecutar(codigo, { nodos: nodos, json: json, env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } })[0].json.debe_publicar, false);
  assert.strictEqual(ejecutar(codigo, { nodos: nodos, json: json })[0].json.debe_publicar, true);
});

test('BACKEND: debe_publicar=false en CONTROL1 con SHADOW=true aunque modo=official', function () {
  const codigo = codigoDe('DECIDIR - Publicar CONTROL1 oficial');
  const nodos = {
    'WEBHOOK control1': [{ json: { body: { modo: 'official' } } }],
    'RESOLVER control1 (periodo y carpetas)': [{ json: { nombre_revision: 'REVISION_X.xlsx', nombre_detalle: 'DETALLE_X.json', nombre_global: 'G.xlsx', mes_nombre: 'SEPTIEMBRE', anio: '2026' } }],
  };
  const json = { data: { revision_actualizada: true, ruta_revision: '/x/REVISION_X.xlsx', detalle_json: '/x/DETALLE_X.json' } };
  assert.strictEqual(ejecutar(codigo, { nodos: nodos, json: json, env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } })[0].json.debe_publicar, false);
  assert.strictEqual(ejecutar(codigo, { nodos: nodos, json: json })[0].json.debe_publicar, true);
});

test('BACKEND: debe_publicar=false en CONTROL3 con SHADOW=true aunque modo=official', function () {
  const codigo = codigoDe('DECIDIR - Publicar CONTROL3 oficial');
  const nodos = {
    'WEBHOOK control3': [{ json: { body: { modo: 'official' } } }],
    'RESOLVER control3 (periodo y carpetas)': [{ json: { nombre_reporte: 'REPORTE.xlsx', nombre_reporte_json: 'REPORTE.json' } }],
  };
  const json = { data: { archivo_control_xlsx: '/x/REPORTE.xlsx', archivo_control_json: '/x/REPORTE.json' } };
  assert.strictEqual(ejecutar(codigo, { nodos: nodos, json: json, env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } })[0].json.debe_publicar, false);
  assert.strictEqual(ejecutar(codigo, { nodos: nodos, json: json })[0].json.debe_publicar, true);
});

console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

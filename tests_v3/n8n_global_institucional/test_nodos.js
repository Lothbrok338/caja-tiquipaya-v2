/**
 * tests_v3/n8n_global_institucional/test_nodos.js -- GENERAR GLOBAL
 * institucional (un solo botón, tres SAP GLOBAL: TIQ/AME/INSTITUCIONAL).
 *
 * Ejecuta, con Node puro (sin n8n, sin Drive), el código REAL de los nodos
 * Code del NUEVO webhook `/global-institucional`. Además verifica que ese
 * mismo texto es el que está desplegado en el snapshot de BACKEND DEV
 * (snapshots/railway-shadow/aLs1f3GMqswbaENA_backend_dev.json) -- mismo
 * patrón que tests_v3/n8n_global_fuente_drive/test_nodos.js.
 *
 * También verifica que la cadena de materialización Drive por caja
 * (RESOLVER carpeta SAP oficial / BUSCAR / DESCARGAR / ESCRIBIR / RESTAURAR)
 * SIGUE existiendo una única vez en el workflow -- esta orquestación NUEVA
 * no la duplicó ni la reemplazó.
 *
 * Uso: node tests_v3/n8n_global_institucional/test_nodos.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const dirNodos = path.join(__dirname, 'nodos');
const snapshotPath = path.join(__dirname, '..', '..', 'snapshots', 'railway-shadow', 'aLs1f3GMqswbaENA_backend_dev.json');

function cargar(nombre) { return fs.readFileSync(path.join(dirNodos, nombre + '.js'), 'utf8'); }

function ejecutar(codigo, opts) {
  opts = opts || {};
  const nodos = opts.nodos || {};
  const entradas = opts.entradas || [{ json: opts.json || {} }];
  const env = opts.env || {};
  const $ = function (nombre) {
    if (!(nombre in nodos)) throw new Error('nodo no mockeado: ' + nombre);
    const items = nodos[nombre];
    return { first: function () { return items[0]; }, all: function () { return items; }, item: items[0] };
  };
  const $input = { all: function () { return entradas; }, first: function () { return entradas[0]; } };
  const $json = entradas[0].json;
  return new Function('$', '$input', '$json', '$execution', '$env', 'Buffer', codigo)(
    $, $input, $json, { id: 'test-1' }, env, Buffer,
  );
}

let pasados = 0, fallidos = 0;
function test(nombre, fn) {
  try { fn(); pasados++; console.log('PASS - ' + nombre); }
  catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); }
}

// ---------------------------------------------------------------------------
// payload.js -- el navegador SOLO manda anio/mes, NUNCA caja.
// ---------------------------------------------------------------------------

test('payload: nunca lee ni propaga body.caja (flujo mensual institucional no depende del selector)', function () {
  const codigo = cargar('payload');
  assert.ok(!codigo.includes('.caja'), 'el payload institucional no debe referenciar body.caja');
  const r = ejecutar(codigo, { json: { body: { anio: 2026, mes: 9, caja: 'america' } } })[0].json;
  const payload = JSON.parse(Buffer.from(r.input_b64, 'base64').toString('utf8'));
  assert.deepStrictEqual(Object.keys(payload).sort(), ['anio', 'base_dir_dev', 'mes', 'ruta_plantilla_origen']);
  assert.strictEqual(payload.anio, 2026);
  assert.strictEqual(payload.mes, 9);
});

// ---------------------------------------------------------------------------
// decidir.js -- shadow guard + los TRES resultados validados antes de
// publicar; nunca institucional parcial.
// ---------------------------------------------------------------------------

const dataOk = function () {
  return {
    resultado_tiq: { estado: 'VALIDADO_PENDIENTE_PUBLICACION', ruta_resultado_json: '/x/RESULTADO_TIQ.json' },
    resultado_ame: { estado: 'VALIDADO_PENDIENTE_PUBLICACION', ruta_resultado_json: '/x/RESULTADO_AME.json' },
    ruta_global_tiq: '/x/SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx',
    ruta_global_ame: '/x/SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx',
    ruta_global_institucional: '/x/SAP_GLOBAL_INSTITUCIONAL_SEPTIEMBRE_2026.xlsx',
    ruta_mapa_origen_institucional: '/x/MAPA_ORIGEN_INSTITUCIONAL_SEPTIEMBRE_2026.json',
  };
};

test('decidir: modo=official + TIQ/AME validados -> debe_publicar=true', function () {
  const nodos = { 'WEBHOOK global institucional': [{ json: { body: { modo: 'official' } } }] };
  const r = ejecutar(cargar('decidir'), { nodos: nodos, json: { data: dataOk() } })[0].json;
  assert.strictEqual(r.debe_publicar, true);
});

test('decidir: modo=dev -> nunca publica, aunque TIQ/AME esten validados', function () {
  const nodos = { 'WEBHOOK global institucional': [{ json: { body: { modo: 'dev' } } }] };
  const r = ejecutar(cargar('decidir'), { nodos: nodos, json: { data: dataOk() } })[0].json;
  assert.strictEqual(r.debe_publicar, false);
});

test('decidir: SHADOW (TIQ_BLOCK_OFFICIAL_PUBLISH=true) -> debe_publicar=false aunque modo=official', function () {
  const nodos = { 'WEBHOOK global institucional': [{ json: { body: { modo: 'official' } } }] };
  const r = ejecutar(cargar('decidir'), { nodos: nodos, json: { data: dataOk() }, env: { TIQ_BLOCK_OFFICIAL_PUBLISH: 'true' } })[0].json;
  assert.strictEqual(r.debe_publicar, false);
});

test('decidir: TIQ sin validar -> debe_publicar=false (nunca institucional parcial)', function () {
  const data = dataOk();
  data.resultado_tiq.estado = 'ERROR_REVISAR';
  const nodos = { 'WEBHOOK global institucional': [{ json: { body: { modo: 'official' } } }] };
  const r = ejecutar(cargar('decidir'), { nodos: nodos, json: { data: data } })[0].json;
  assert.strictEqual(r.debe_publicar, false);
});

test('decidir: AME sin validar -> debe_publicar=false (nunca institucional parcial)', function () {
  const data = dataOk();
  data.resultado_ame.estado = 'ERROR_REVISAR';
  const nodos = { 'WEBHOOK global institucional': [{ json: { body: { modo: 'official' } } }] };
  const r = ejecutar(cargar('decidir'), { nodos: nodos, json: { data: data } })[0].json;
  assert.strictEqual(r.debe_publicar, false);
});

// ---------------------------------------------------------------------------
// lista.js -- los TRES GLOBAL + su resultado/mapa de origen, a la MISMA
// carpeta institucional GLOBAL. Naming correcto de los tres.
// ---------------------------------------------------------------------------

const decidirOk = function () {
  const nodos = { 'WEBHOOK global institucional': [{ json: { body: { modo: 'official' } } }] };
  return ejecutar(cargar('decidir'), { nodos: nodos, json: { data: dataOk() } })[0].json;
};

test('lista: construye 6 publicaciones (3 GLOBAL + resultado/mapa de origen) a la misma carpeta', function () {
  const nodos = { 'DECIDIR - Publicar GLOBAL institucional oficial': [{ json: decidirOk() }] };
  const items = ejecutar(cargar('lista'), { nodos: nodos, json: { carpeta_id: 'CARPETA_GLOBAL_INSTITUCIONAL' } });
  assert.strictEqual(items.length, 6);
  items.forEach(function (it) { assert.strictEqual(it.json.carpeta_id, 'CARPETA_GLOBAL_INSTITUCIONAL'); });
  const nombres = items.map(function (it) { return it.json.nombre_archivo; });
  assert.ok(nombres.includes('SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx'));
  assert.ok(nombres.includes('SAP_GLOBAL_AME_SEPTIEMBRE_2026.xlsx'));
  assert.ok(nombres.includes('SAP_GLOBAL_INSTITUCIONAL_SEPTIEMBRE_2026.xlsx'));
});

// ---------------------------------------------------------------------------
// Sincronía con el snapshot desplegado + no duplicación de nodos/workflows.
// ---------------------------------------------------------------------------

test('el codigo desplegado en el snapshot de BACKEND DEV coincide con estos archivos', function () {
  const snap = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
  const porNombre = {};
  for (const n of snap.nodes) porNombre[n.name] = n;

  const mapa = {
    'CONSTRUIR payload global institucional': 'payload',
    'DECIDIR - Publicar GLOBAL institucional oficial': 'decidir',
    'CONSTRUIR - Lista publicaciones GLOBAL institucional': 'lista',
    'COMBINAR - Resultado GLOBAL institucional con Drive': 'combinar_con',
    'COMBINAR - Resultado GLOBAL institucional sin Drive': 'combinar_sin',
  };
  Object.keys(mapa).forEach(function (nombreNodo) {
    const desplegado = porNombre[nombreNodo].parameters.jsCode;
    assert.strictEqual(desplegado, cargar(mapa[nombreNodo]), 'desincronizado: ' + nombreNodo);
  });
});

test('la orquestacion institucional NO duplico ni reemplazo la materializacion Drive por caja', function () {
  const snap = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
  const nombres = snap.nodes.map(function (n) { return n.name; });
  // exactamente UNA vez cada uno -- nunca una segunda copia para AMERICA.
  ['RESOLVER carpeta SAP oficial', 'BUSCAR - SAP oficiales del mes (Drive)',
   'FILTRAR - SAP diarios validos del periodo', 'DESCARGAR - SAP oficial (Drive)',
   'ESCRIBIR - SAP a global_entrada'].forEach(function (nombre) {
    const veces = nombres.filter(function (n) { return n === nombre; }).length;
    assert.strictEqual(veces, 1, nombre + ' aparece ' + veces + ' veces (se esperaba 1: sin duplicar)');
  });
  // generar_global()/CONSTRUIR payload global (por caja) siguen intactos: el
  // flujo diario/por-caja no fue tocado por esta orquestacion nueva.
  assert.ok(nombres.includes('WEBHOOK global'));
  assert.ok(nombres.includes('CONSTRUIR payload global'));
  // la nueva orquestacion es un webhook mas, no un workflow nuevo.
  assert.strictEqual(snap.id, 'aLs1f3GMqswbaENA');
});

test('flujo diario sigue enviando caja: CONSTRUIR payload global (por caja) no cambio', function () {
  const snap = JSON.parse(fs.readFileSync(snapshotPath, 'utf8'));
  const porNombre = {};
  for (const n of snap.nodes) porNombre[n.name] = n;
  const codigo = porNombre['CONSTRUIR payload global'].parameters.jsCode;
  assert.ok(codigo.includes("caja: t.body.caja || 'tiquipaya'"));
});

console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

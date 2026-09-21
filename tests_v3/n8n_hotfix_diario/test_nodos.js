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
function ejecutar(codigo, nodos, entradas, json, env) {
  const $ = function (nombre) {
    if (!(nombre in nodos)) throw new Error('nodo no mockeado: ' + nombre);
    const items = nodos[nombre];
    return { first: function () { return items[0]; }, all: function () { return items; }, item: items[0] };
  };
  const $input = { all: function () { return entradas || []; }, first: function () { return (entradas || [])[0]; } };
  return new Function('$', '$input', '$json', '$execution', '$env', 'Buffer', codigo)($, $input, json || {}, { id: 'test-1' }, env || {}, Buffer);
}
let pasados = 0, fallidos = 0;
function test(nombre, fn) { try { fn(); pasados++; console.log('PASS - ' + nombre); } catch (e) { fallidos++; console.log('FAIL - ' + nombre + '\n       ' + (e && e.stack || e)); } }
function assertLanza(fn, subcadenaEsperada) {
  let lanzo = false;
  try { fn(); } catch (err) {
    lanzo = true;
    assert.ok(err.message.indexOf(subcadenaEsperada) !== -1, 'mensaje de error no contiene "' + subcadenaEsperada + '": ' + err.message);
  }
  assert.ok(lanzo, 'se esperaba que lanzara un error y no lanzo nada');
}

// -----------------------------------------------------------------------
// CONTRATO /procesar: caja EXPLICITA obligatoria (nodo "CONSTRUIR payload
// crear_lote_pendiente"). A diferencia del default historico de Python
// (config_cajas.resolver_caja(None) -> TIQUIPAYA, que sigue vivo para
// otras APIs/fixtures legacy), esta ruta HTTP nunca debe crear un lote ni
// invocar Python si la caja llega ausente o invalida.
// -----------------------------------------------------------------------
const construirPayloadCrearLote = function (bodyCaja, restoBody) {
  const body = Object.assign({ fecha_inicio: '2026-09-12', fecha_fin: '2026-09-12' }, restoBody, { caja: bodyCaja });
  return ejecutar(cargar('construir_payload_crear_lote_pendiente'), {}, [{ json: { body: body } }]);
};

test('crear_lote_pendiente: caja "tiquipaya" explicita se acepta y se normaliza igual', function () {
  const p = construirPayloadCrearLote('tiquipaya')[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(pl.caja, 'tiquipaya');
});

test('crear_lote_pendiente: caja "AMERICA" (mayusculas/espacios) se acepta y se normaliza a "america"', function () {
  const p = construirPayloadCrearLote('  AMERICA  ')[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(pl.caja, 'america');
});

test('crear_lote_pendiente: SIN caja -> CAJA_REQUERIDA_EN_PROCESAR, nunca crea el lote (no llega a devolver payload)', function () {
  assertLanza(function () { construirPayloadCrearLote(undefined); }, 'CAJA_REQUERIDA_EN_PROCESAR');
  assertLanza(function () { construirPayloadCrearLote(null); }, 'CAJA_REQUERIDA_EN_PROCESAR');
  assertLanza(function () { construirPayloadCrearLote(''); }, 'CAJA_REQUERIDA_EN_PROCESAR');
});

test('crear_lote_pendiente: caja invalida ("brasil") -> CAJA_REQUERIDA_EN_PROCESAR, nunca se adivina', function () {
  assertLanza(function () { construirPayloadCrearLote('brasil'); }, 'CAJA_REQUERIDA_EN_PROCESAR');
});

const LOTE = 'abc123def456';
const base = function (fechaInicio, caja) {
  return {
    'INTERPRETAR resultado crear_lote_pendiente': [{ json: { data: { lote_id: LOTE, caja: caja } } }],
    'WEBHOOK procesar': [{ json: { body: { fecha_inicio: fechaInicio || '2026-09-12', fecha_fin: '2026-09-12' } } }],
  };
};
const RP = ejecutar(cargar('resolver_procesar'), base())[0].json;
const ING = function (cierres) { return { 'EJECUTAR - 01 INGESTA (Drive real)': [{ json: { data: { cierres: cierres } } }] }; };

// -----------------------------------------------------------------------
// MACROS mensual generico: carpeta raiz -> carpeta del anio -> carpeta del
// mes -> archivo "MACROS*.xlsm/.xlsx" -- cada nivel 0/>1 = falla cerrado.
// -----------------------------------------------------------------------
const dr = function (nombres) { return (nombres || []).map(function (n, i) { return { json: { id: 'd' + i, name: n } }; }); };
const verificarAnio = function (rp, nombresAnio) {
  const nodos = { 'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: rp }], 'BUSCAR - Carpeta anio MACROS (Drive)': dr(nombresAnio) };
  return ejecutar(cargar('verificar_carpeta_anio_macros'), nodos, [])[0].json;
};
const verificarMes = function (rp, verifAnio, nombresMes) {
  const nodos = { 'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: rp }], 'VERIFICAR - Carpeta anio MACROS': [{ json: verifAnio }],
    'BUSCAR - Carpeta mes MACROS (Drive)': dr(nombresMes) };
  return ejecutar(cargar('verificar_carpeta_mes_macros'), nodos, [])[0].json;
};
const clasif = function (macros, cierres, rp, verifMes) {
  const rpUsado = rp || RP;
  const verifMesUsado = verifMes || { hay_error: false, carpeta_mes_id: 'mes-1' };
  const nodos = Object.assign({ 'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: rpUsado }],
    'VERIFICAR - Carpeta mes MACROS': [{ json: verifMesUsado }],
    'BUSCAR MACROS oficial (Drive)': macros.map(function (n, i) { return { json: n === null ? {} : { id: 'm' + i, name: n } }; }) }, ING(cierres));
  return ejecutar(cargar('clasificar_procesar'), nodos, []).map(function (i) { return i.json; });
};
const ENC = function (fecha, id) { return { fecha: fecha, estado_ingesta: 'ENCONTRADO', drive_file_id: id, archivo_esperado: 'CIERRE ' + fecha.slice(8) + '-' + fecha.slice(5, 7) + '-' + fecha.slice(0, 4) + '.xlsm' }; };

test('resolver: periodo/anio + carpeta raiz institucional de MACROS; entrada aislada por lote', function () {
  assert.strictEqual(RP.periodo, '2026-09');
  assert.strictEqual(RP.anio, '2026');
  assert.strictEqual(RP.macros_raiz_id, '1XOlFEKP3nKSvbHCEpk5l8BKWhOMbhMZB');
  assert.ok(RP.dir_entrada.endsWith('/dev_workdir/procesar_entrada/' + LOTE));
  assert.strictEqual(RP.dir_cierres, RP.dir_entrada + '/cierres');
  assert.ok(!/maestro_origen|cierres_origen|publicacion\//.test(RP.dir_entrada));
});
test('resolver: cualquier mes deriva su propio periodo/anio -- nunca un fallback fijo a septiembre 2026', function () {
  const dic = ejecutar(cargar('resolver_procesar'), base('2026-12-05'))[0].json;
  assert.strictEqual(dic.periodo, '2026-12');
  assert.strictEqual(dic.anio, '2026');
  assert.strictEqual(dic.macros_raiz_id, RP.macros_raiz_id); // misma raiz institucional, cualquier mes
  const otroAnio = ejecutar(cargar('resolver_procesar'), base('2027-01-10'))[0].json;
  assert.strictEqual(otroAnio.periodo, '2027-01');
  assert.strictEqual(otroAnio.anio, '2027');
});
test('resolver: DRIVE_MACROS_RAIZ del entorno reemplaza el default institucional', function () {
  const r = ejecutar(cargar('resolver_procesar'), base(), null, null, { DRIVE_MACROS_RAIZ: 'raiz-alterna' })[0].json;
  assert.strictEqual(r.macros_raiz_id, 'raiz-alterna');
});
test('verificar anio: 1 carpeta exacta -> se usa; 0 -> falla cerrado; >1 -> ambiguo (nunca elige la primera)', function () {
  const ok = verificarAnio(RP, ['2026']);
  assert.deepStrictEqual(ok, { hay_error: false, carpeta_anio_id: 'd0' });
  const sinAnio = verificarAnio(RP, []);
  assert.strictEqual(sinAnio.hay_error, true); assert.match(sinAnio.mensaje_error, /MACROS_CARPETA_ANIO_NO_ENCONTRADA/);
  const otroAnio = verificarAnio(RP, ['2025']);
  assert.strictEqual(otroAnio.hay_error, true); assert.match(otroAnio.mensaje_error, /MACROS_CARPETA_ANIO_NO_ENCONTRADA/);
  const ambiguo = verificarAnio(RP, ['2026', '2026']);
  assert.strictEqual(ambiguo.hay_error, true); assert.match(ambiguo.mensaje_error, /ERROR_AMBIGUO_CARPETA_ANIO_MACROS/);
});
test('verificar mes: 1 carpeta "YYYY-MM" exacta -> se usa; 0/>1 -> falla cerrado; propaga el error del anio sin volver a buscar', function () {
  const verifAnio = verificarAnio(RP, ['2026']);
  const ok = verificarMes(RP, verifAnio, ['2026-09']);
  assert.deepStrictEqual(ok, { hay_error: false, carpeta_mes_id: 'd0' });
  const sinMes = verificarMes(RP, verifAnio, []);
  assert.strictEqual(sinMes.hay_error, true); assert.match(sinMes.mensaje_error, /MACROS_OFICIAL_NO_CONFIGURADO/);
  const ambiguo = verificarMes(RP, verifAnio, ['2026-09', '2026-09']);
  assert.strictEqual(ambiguo.hay_error, true); assert.match(ambiguo.mensaje_error, /ERROR_AMBIGUO_CARPETA_MES_MACROS/);
  const anioFallido = { hay_error: true, mensaje_error: 'MACROS_CARPETA_ANIO_NO_ENCONTRADA: x' };
  assert.deepStrictEqual(verificarMes(RP, anioFallido, ['2026-09']), anioFallido);
});
test('clasificar: MACROS por PREFIJO (nunca nombre exacto fijo) + cierres ENCONTRADOS -> descargas con su id exacto y ruta en procesar_entrada', function () {
  const c = clasif(['MACROS SEPTIEMBRE.xlsm'], [ENC('2026-09-11', 'F11'), ENC('2026-09-12', 'F12'), { fecha: '2026-09-13', estado_ingesta: 'SIN_ARCHIVO' }]);
  assert.deepStrictEqual(c.map(function (i) { return i.tipo + ':' + i.id; }), ['macros:m0', 'cierre:F11', 'cierre:F12']);
  c.forEach(function (i) { assert.strictEqual(i.hay_error, false); assert.ok(i.ruta_destino.indexOf(RP.dir_entrada) === 0); });
  assert.strictEqual(c[0].ruta_destino, RP.dir_entrada + '/MACROS SEPTIEMBRE.xlsm');
  assert.strictEqual(c[2].ruta_destino, RP.dir_cierres + '/CIERRE 12-09-2026.xlsm');
});
test('clasificar: nombre distinto de MACROS SEPTIEMBRE (p.ej. otro mes real "MACROS AGOSTO 2026.xlsm") tambien resuelve por prefijo', function () {
  const c = clasif(['MACROS AGOSTO 2026.xlsm'], [ENC('2026-08-11', 'F11')]);
  assert.strictEqual(c[0].name, 'MACROS AGOSTO 2026.xlsm');
  assert.strictEqual(c[0].ruta_destino, RP.dir_entrada + '/MACROS AGOSTO 2026.xlsm');
});
test('clasificar: si la carpeta del mes ya fallo (hay_error), no vuelve a tocar Drive: propaga el mismo mensaje', function () {
  const mesFallido = { hay_error: true, mensaje_error: 'MACROS_OFICIAL_NO_CONFIGURADO: no hay carpeta para 2026-10' };
  const c = clasif([], [], RP, mesFallido);
  assert.deepStrictEqual(c, [{ hay_error: true, mensaje_error: mesFallido.mensaje_error }]);
});
test('clasificar: 0 MACROS -> MACROS_OFICIAL_NO_ENCONTRADO; >1 -> ERROR_AMBIGUO_MACROS (nunca elige uno)', function () {
  assert.match(clasif([null], [ENC('2026-09-12', 'F')])[0].mensaje_error, /MACROS_OFICIAL_NO_ENCONTRADO/);
  assert.match(clasif(['OTRO.xlsm'], [ENC('2026-09-12', 'F')])[0].mensaje_error, /MACROS_OFICIAL_NO_ENCONTRADO/);
  assert.match(clasif(['MACROS.docx'], [ENC('2026-09-12', 'F')])[0].mensaje_error, /MACROS_OFICIAL_NO_ENCONTRADO/);
  const amb = clasif(['MACROS SEPTIEMBRE.xlsm', 'MACROS SEPTIEMBRE (copia).xlsm'], [ENC('2026-09-12', 'F')]);
  assert.strictEqual(amb.length, 1); assert.match(amb[0].mensaje_error, /ERROR_AMBIGUO_MACROS/);
});
test('clasificar: solo MACROS si ningun cierre fue ENCONTRADO; sin duplicar el mismo drive_file_id', function () {
  assert.strictEqual(clasif(['MACROS SEPTIEMBRE.xlsm'], [{ fecha: '2026-09-13', estado_ingesta: 'SIN_ARCHIVO' }]).length, 1);
  assert.strictEqual(clasif(['MACROS SEPTIEMBRE.xlsm'], [ENC('2026-09-12', 'F'), ENC('2026-09-12', 'F')]).length, 2);
});
test('payload procesar_lote: origen del cierre y de MACROS = procesar_entrada del lote (nunca las copias estaticas ni un nombre fijo)', function () {
  const nodos = Object.assign(base(), {
    'RESOLVER procesar_entrada (MACROS y cierres)': [{ json: RP }],
    'CLASIFICAR - MACROS y cierres de procesar': [{ json: { hay_error: false, tipo: 'macros', id: 'm0', name: 'MACROS SEPTIEMBRE.xlsm', ruta_destino: RP.dir_entrada + '/MACROS SEPTIEMBRE.xlsm' } },
      { json: { hay_error: false, tipo: 'cierre', id: 'F', name: 'CIERRE 12-09-2026.xlsm', ruta_destino: RP.dir_cierres + '/CIERRE 12-09-2026.xlsm' } }],
  });
  const p = ejecutar(cargar('construir_payload_procesar_lote'), nodos, [{ json: { data: { cierres: [ENC('2026-09-12', 'F')] } } }])[0].json;
  const pl = JSON.parse(Buffer.from(p.input_b64, 'base64').toString('utf8'));
  assert.strictEqual(pl.origen_cierres_dir, RP.dir_cierres);
  assert.strictEqual(pl.ruta_maestro_origen, RP.dir_entrada + '/MACROS SEPTIEMBRE.xlsm');
  assert.ok(!/maestro_origen\/|cierres_origen/.test(JSON.stringify([pl.origen_cierres_dir, pl.ruta_maestro_origen])));
  assert.strictEqual(pl.requiere_ingesta_drive, true); assert.strictEqual(pl.lote_id, LOTE);
  assert.ok(pl.ingesta_precomputada.length === 1);
  assert.ok(!/\.item\b/.test(cargar('construir_payload_procesar_lote')));
});

// -----------------------------------------------------------------------
// AISLAMIENTO DRIVE POR CAJA (nodo "RESOLVER - Drive entrada por caja
// (INGESTA)"): /procesar debe pedirle a 01 INGESTA el folder_entrada de la
// caja PERSISTIDA en el lote (nunca la del request), y AMERICA nunca debe
// heredar el folder de TIQUIPAYA.
// -----------------------------------------------------------------------
const resolverEntrada = function (caja, env) {
  const nodos = { 'INTERPRETAR resultado crear_lote_pendiente': [{ json: { data: { lote_id: LOTE, caja: caja } } }] };
  return ejecutar(cargar('resolver_drive_entrada_por_caja'), nodos, [], null, env)[0].json;
};
test('resolver entrada por caja: TIQUIPAYA (o lote sin caja/historico) resuelve el folder historico de 00_ENTRADA_CIERRES', function () {
  assert.deepStrictEqual(resolverEntrada('tiquipaya', {}), { caja: 'tiquipaya', folder_entrada: '1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1' });
  assert.deepStrictEqual(resolverEntrada(undefined, {}), { caja: 'tiquipaya', folder_entrada: '1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1' });
});
test('resolver entrada por caja: AMERICA con DRIVE_ENTRADA_AME configurada resuelve un folder DISTINTO al de TIQ', function () {
  const r = resolverEntrada('america', { DRIVE_ENTRADA_AME: 'ame-entrada-1' });
  assert.deepStrictEqual(r, { caja: 'america', folder_entrada: 'ame-entrada-1' });
  assert.notStrictEqual(r.folder_entrada, resolverEntrada('tiquipaya', {}).folder_entrada);
});
test('resolver entrada por caja: AMERICA sin DRIVE_ENTRADA_AME falla cerrado, NUNCA hereda el folder de TIQ', function () {
  assertLanza(function () { resolverEntrada('america', {}); }, 'DRIVE_AME_PENDIENTE');
});
test('resolver entrada por caja: caja desconocida falla cerrado, no se adivina', function () {
  assertLanza(function () { resolverEntrada('brasil', {}); }, 'CAJA_DESCONOCIDA');
});
test('resolver entrada por caja: DRIVE_ENTRADA_TIQ en el entorno no afecta a AMERICA ni viceversa', function () {
  const env = { DRIVE_ENTRADA_AME: 'ame-entrada-1', DRIVE_ENTRADA_TIQ: 'override-tiq' };
  assert.strictEqual(resolverEntrada('tiquipaya', env).folder_entrada, 'override-tiq');
  assert.strictEqual(resolverEntrada('america', env).folder_entrada, 'ame-entrada-1');
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
    'CONSTRUIR payload consolidar publicar': 'construir_payload_consolidar', 'RESPUESTA publicar (estado oficial)': 'respuesta_publicar_final',
    'RESOLVER - Drive entrada por caja (INGESTA)': 'resolver_drive_entrada_por_caja',
    'VERIFICAR - Carpeta anio MACROS': 'verificar_carpeta_anio_macros', 'VERIFICAR - Carpeta mes MACROS': 'verificar_carpeta_mes_macros',
    'CONSTRUIR payload crear_lote_pendiente': 'construir_payload_crear_lote_pendiente' };
  Object.keys(mapa).forEach(function (nombre) {
    const nodo = nodos.find(function (n) { return n.name === nombre; });
    if (!nodo) assert.fail('falta nodo ' + nombre);
    assert.strictEqual(nodo.parameters.jsCode.trim(), cargar(mapa[nombre]).trim(), nombre);
  });
  const C = (wf.workflow || wf).connections;
  const sig = function (n, i) { return ((C[n] || {}).main || [])[i || 0].map(function (t) { return t.node; }); };
  assert.deepStrictEqual(sig('INTERPRETAR resultado crear_lote_pendiente', 0).slice(1), ['RESOLVER - Drive entrada por caja (INGESTA)']);
  assert.deepStrictEqual(sig('RESOLVER - Drive entrada por caja (INGESTA)'), ['EJECUTAR - 01 INGESTA (Drive real)']);
  assert.deepStrictEqual(sig('EJECUTAR - 01 INGESTA (Drive real)'), ['RESOLVER procesar_entrada (MACROS y cierres)']);
  assert.deepStrictEqual(sig('PREPARAR procesar_entrada limpio (Python)'), ['BUSCAR - Carpeta anio MACROS (Drive)']);
  assert.deepStrictEqual(sig('BUSCAR - Carpeta anio MACROS (Drive)'), ['VERIFICAR - Carpeta anio MACROS']);
  assert.deepStrictEqual(sig('VERIFICAR - Carpeta anio MACROS'), ['BUSCAR - Carpeta mes MACROS (Drive)']);
  assert.deepStrictEqual(sig('BUSCAR - Carpeta mes MACROS (Drive)'), ['VERIFICAR - Carpeta mes MACROS']);
  assert.deepStrictEqual(sig('VERIFICAR - Carpeta mes MACROS'), ['BUSCAR MACROS oficial (Drive)']);
  assert.deepStrictEqual(sig('BUSCAR MACROS oficial (Drive)'), ['CLASIFICAR - MACROS y cierres de procesar']);
  assert.deepStrictEqual(sig('RESTAURAR - Ingesta para procesar'), ['CONSTRUIR payload procesar_lote']);
  assert.deepStrictEqual(sig('CONSTRUIR - Respuesta sin Drive oficial'), ['CONSTRUIR payload consolidar publicar']);
  assert.deepStrictEqual(sig('COMBINAR - Resultado local + Drive oficial'), ['CONSTRUIR payload consolidar publicar']);
  assert.deepStrictEqual(sig('RESPUESTA publicar (estado oficial)'), ['RESPONDER publicar']);
});
console.log('\n' + pasados + ' passed, ' + fallidos + ' failed');
process.exit(fallidos ? 1 : 0);

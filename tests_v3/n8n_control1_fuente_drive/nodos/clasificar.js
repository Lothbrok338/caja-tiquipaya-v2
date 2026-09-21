// CONTROL 1 institucional: exige EXACTAMENTE un GLOBAL TIQ y un GLOBAL AME
// oficiales (ambos, mismo periodo); el historico institucional UNICO (raiz
// de 05_CONTROLES) es opcional (0 o 1, nunca mas de uno). Nunca lee
// REVISION_ASIGNACIONES: eso es del flujo legacy por-caja (ejecutar_control1),
// CONTROL 1 institucional no lo usa.
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
function exactos(nodo, nombre) {
  let items;
  try { items = $(nodo).all(); } catch (e) { items = []; }
  return items.map(function (i) { return i.json; }).filter(function (j) { return j && j.id && j.name === nombre; });
}
const gTiq = exactos('BUSCAR GLOBAL oficial (Drive)', rc.nombre_global_tiq);
const gAme = exactos('BUSCAR GLOBAL AME oficial (Drive)', rc.nombre_global_ame);
const h = exactos('BUSCAR historico asignaciones (Drive)', rc.nombre_historico);

if (gTiq.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 1 institucional no usa un GLOBAL local como sustituto: genera ambos GLOBAL antes.');
}
if (gTiq.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gTiq.length + ' archivos "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (gAme.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 1 institucional no usa un GLOBAL local como sustituto: genera ambos GLOBAL antes.');
}
if (gAme.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gAme.length + ' archivos "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (h.length > 1) {
  throw new Error('ERROR_AMBIGUO_HISTORICO: hay ' + h.length + ' archivos "' + rc.nombre_historico + '" en 05_CONTROLES. No se elige ninguno.');
}

const items = [
  { tipo: 'global_tiq', id: String(gTiq[0].id), name: rc.nombre_global_tiq },
  { tipo: 'global_ame', id: String(gAme[0].id), name: rc.nombre_global_ame },
];
if (h.length === 1) items.push({ tipo: 'historico', id: String(h[0].id), name: rc.nombre_historico });
return items.map(function (it) {
  return { json: Object.assign({ ruta_destino: rc.dir_entrada + '/' + it.name, historico_en_drive: h.length === 1 }, it) };
});

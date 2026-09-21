// Exige EXACTAMENTE los dos GLOBAL oficiales (TIQ y AME): CONTROL 1
// institucional audita ambas cajas juntas y nunca sustituye ninguno por un
// GLOBAL local. El historico institucional (raiz de 05_CONTROLES) y el
// estado sellado del periodo (carpeta <YYYY-MM>) son opcionales (0 o 1) --
// ausentes = primera ejecucion legitima.
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
function exactos(nodo, nombre) {
  let items;
  try { items = $(nodo).all(); } catch (e) { items = []; } // p.ej. no existe la carpeta del periodo: la busqueda de estado no corrio
  return items.map(function (i) { return i.json; }).filter(function (j) { return j && j.id && j.name === nombre; });
}
const gTiq = exactos('BUSCAR GLOBAL TIQ oficial (Drive)', rc.nombre_global_tiq);
const gAme = exactos('BUSCAR GLOBAL AME oficial (Drive)', rc.nombre_global_ame);
const h = exactos('BUSCAR historico institucional (Drive)', rc.nombre_historico);
const e = exactos('BUSCAR estado del periodo (Drive)', rc.nombre_estado);

if (gTiq.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 1 institucional nunca usa un GLOBAL local como sustituto: genera el GLOBAL TIQUIPAYA antes.');
}
if (gTiq.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gTiq.length + ' archivos "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (gAme.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 1 institucional nunca usa un GLOBAL local como sustituto: genera el GLOBAL AMERICA antes.');
}
if (gAme.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gAme.length + ' archivos "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (h.length > 1) {
  throw new Error('ERROR_AMBIGUO_HISTORICO: hay ' + h.length + ' archivos "' + rc.nombre_historico + '" en 05_CONTROLES. No se elige ninguno.');
}
if (e.length > 1) {
  throw new Error('ERROR_AMBIGUO_ESTADO: hay ' + e.length + ' archivos "' + rc.nombre_estado + '" en CONTROL_1_ASIGNACIONES/' + rc.periodo + '. No se elige ninguno.');
}

const items = [
  { tipo: 'global_tiq', id: String(gTiq[0].id), name: rc.nombre_global_tiq },
  { tipo: 'global_ame', id: String(gAme[0].id), name: rc.nombre_global_ame },
];
if (h.length === 1) items.push({ tipo: 'historico', id: String(h[0].id), name: rc.nombre_historico });
if (e.length === 1) items.push({ tipo: 'estado', id: String(e[0].id), name: rc.nombre_estado });
return items.map(function (it) {
  return { json: Object.assign({ ruta_destino: rc.dir_entrada + '/' + it.name, historico_en_drive: h.length === 1, estado_en_drive: e.length === 1 }, it) };
});

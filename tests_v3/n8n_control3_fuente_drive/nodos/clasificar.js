// Exige EXACTAMENTE los dos GLOBAL oficiales (TIQ y AME): CONTROL 3
// institucional audita ambas cajas juntas y nunca sustituye ninguno por un
// GLOBAL local. Los historicos MAESTROS (raiz de 05_CONTROLES) y el reporte
// previo del periodo (carpeta <YYYY-MM>) son opcionales (0 o 1), nunca mas de
// uno. Los snapshots por periodo nunca se buscan aqui.
const rc = $('RESOLVER control3 (periodo y carpetas)').first().json;
function exactos(nodo, nombre) {
  let items;
  try { items = $(nodo).all(); } catch (e) { items = []; } // p.ej. no existe la carpeta del periodo: la busqueda del reporte no corrio
  return items.map(function (i) { return i.json; }).filter(function (j) { return j && j.id && j.name === nombre; });
}
const gTiq = exactos('BUSCAR GLOBAL TIQ oficial CONTROL3 (Drive)', rc.nombre_global_tiq);
const gAme = exactos('BUSCAR GLOBAL AME oficial CONTROL3 (Drive)', rc.nombre_global_ame);
const h = exactos('BUSCAR historico CxC/CxP maestro (Drive)', rc.nombre_historico);
const p = exactos('BUSCAR periodos CxC/CxP maestro (Drive)', rc.nombre_periodos);
const r = exactos('BUSCAR reporte del periodo CONTROL3 (Drive)', rc.nombre_reporte);

if (gTiq.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 3 institucional nunca usa un GLOBAL local como sustituto: genera el GLOBAL TIQUIPAYA antes.');
}
if (gTiq.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gTiq.length + ' archivos "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (gAme.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 3 institucional nunca usa un GLOBAL local como sustituto: genera el GLOBAL AMERICA antes.');
}
if (gAme.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gAme.length + ' archivos "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (h.length > 1) {
  throw new Error('ERROR_AMBIGUO_HISTORICO: hay ' + h.length + ' archivos "' + rc.nombre_historico + '" en 05_CONTROLES. No se elige ninguno.');
}
if (p.length > 1) {
  throw new Error('ERROR_AMBIGUO_PERIODOS: hay ' + p.length + ' archivos "' + rc.nombre_periodos + '" en 05_CONTROLES. No se elige ninguno.');
}
if (r.length > 1) {
  throw new Error('ERROR_AMBIGUO_REPORTE: hay ' + r.length + ' archivos "' + rc.nombre_reporte + '" en CONTROL_3_CXC_CXP/' + rc.periodo + '. No se elige ninguno.');
}
// Un histórico sin su libro de periodos (o al revés) es un estado incoherente: no se adivina cuál manda.
if (h.length !== p.length) {
  throw new Error('MAESTROS_CXC_CXP_INCOMPLETOS: en 05_CONTROLES hay ' + h.length + ' "' + rc.nombre_historico + '" y ' + p.length + ' "' + rc.nombre_periodos + '". Deben existir ambos o ninguno.');
}

const items = [
  { tipo: 'global_tiq', id: String(gTiq[0].id), name: rc.nombre_global_tiq },
  { tipo: 'global_ame', id: String(gAme[0].id), name: rc.nombre_global_ame },
];
if (h.length === 1) items.push({ tipo: 'historico', id: String(h[0].id), name: rc.nombre_historico });
if (p.length === 1) items.push({ tipo: 'periodos', id: String(p[0].id), name: rc.nombre_periodos });
if (r.length === 1) items.push({ tipo: 'reporte', id: String(r[0].id), name: rc.nombre_reporte });
return items.map(function (it) {
  return { json: Object.assign({ ruta_destino: rc.dir_entrada + '/' + it.name, maestros_en_drive: h.length === 1, reporte_en_drive: r.length === 1 }, it) };
});

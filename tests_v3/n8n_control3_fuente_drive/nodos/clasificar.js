// CONTROL 3 institucional: exige EXACTAMENTE un GLOBAL TIQ y un GLOBAL AME
// oficiales (ambos, mismo periodo). Los historicos MAESTROS (raiz de
// 05_CONTROLES) ya son institucionales/compartidos (mismo nombre que el
// flujo legacy): opcionales (0 o 1 cada uno), nunca mas de uno. El reporte
// previo del periodo NUNCA se lee aqui: ejecutar_control3_institucional
// genera su propio reporte institucional, no depende de uno anterior.
const rc = $('RESOLVER control3 (periodo y carpetas)').first().json;
function exactos(nodo, nombre) {
  let items;
  try { items = $(nodo).all(); } catch (e) { items = []; }
  return items.map(function (i) { return i.json; }).filter(function (j) { return j && j.id && j.name === nombre; });
}
const gTiq = exactos('BUSCAR GLOBAL oficial CONTROL3 (Drive)', rc.nombre_global_tiq);
const gAme = exactos('BUSCAR GLOBAL AME oficial CONTROL3 (Drive)', rc.nombre_global_ame);
const h = exactos('BUSCAR historico CxC/CxP maestro (Drive)', rc.nombre_historico);
const p = exactos('BUSCAR periodos CxC/CxP maestro (Drive)', rc.nombre_periodos);

if (gTiq.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 3 institucional no usa un GLOBAL local como sustituto: genera ambos GLOBAL antes.');
}
if (gTiq.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + gTiq.length + ' archivos "' + rc.nombre_global_tiq + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (gAme.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global_ame + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 3 institucional no usa un GLOBAL local como sustituto: genera ambos GLOBAL antes.');
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
if (h.length !== p.length) {
  throw new Error('MAESTROS_CXC_CXP_INCOMPLETOS: en 05_CONTROLES hay ' + h.length + ' "' + rc.nombre_historico + '" y ' + p.length + ' "' + rc.nombre_periodos + '". Deben existir ambos o ninguno.');
}

const items = [
  { tipo: 'global_tiq', id: String(gTiq[0].id), name: rc.nombre_global_tiq },
  { tipo: 'global_ame', id: String(gAme[0].id), name: rc.nombre_global_ame },
];
if (h.length === 1) items.push({ tipo: 'historico', id: String(h[0].id), name: rc.nombre_historico });
if (p.length === 1) items.push({ tipo: 'periodos', id: String(p[0].id), name: rc.nombre_periodos });
return items.map(function (it) {
  return { json: Object.assign({ ruta_destino: rc.dir_entrada + '/' + it.name, maestros_en_drive: h.length === 1 }, it) };
});

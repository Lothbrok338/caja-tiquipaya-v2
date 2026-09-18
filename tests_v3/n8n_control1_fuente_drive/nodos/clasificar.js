// Exige EXACTAMENTE un GLOBAL oficial; historico y revision son opcionales (0 o 1), nunca mas de uno.
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
function exactos(nodo, nombre) {
  return $(nodo).all().map(function (i) { return i.json; }).filter(function (j) { return j && j.id && j.name === nombre; });
}
const g = exactos('BUSCAR GLOBAL oficial (Drive)', rc.nombre_global);
const h = exactos('BUSCAR historico asignaciones (Drive)', rc.nombre_historico);
const r = exactos('BUSCAR revision del periodo (Drive)', rc.nombre_revision);

if (g.length === 0) {
  throw new Error('GLOBAL_OFICIAL_NO_ENCONTRADO: no existe "' + rc.nombre_global + '" en 05_CONTROLES/GLOBAL de Drive. CONTROL 1 no usa un GLOBAL local como sustituto: genera el GLOBAL antes.');
}
if (g.length > 1) {
  throw new Error('ERROR_AMBIGUO_GLOBAL: hay ' + g.length + ' archivos "' + rc.nombre_global + '" en 05_CONTROLES/GLOBAL. No se elige ninguno.');
}
if (h.length > 1) {
  throw new Error('ERROR_AMBIGUO_HISTORICO: hay ' + h.length + ' archivos "' + rc.nombre_historico + '" en 05_CONTROLES. No se elige ninguno.');
}
if (r.length > 1) {
  throw new Error('ERROR_AMBIGUO_REVISION: hay ' + r.length + ' archivos "' + rc.nombre_revision + '" en CONTROL_1_ASIGNACIONES. No se elige ninguno.');
}

const items = [{ tipo: 'global', id: String(g[0].id), name: rc.nombre_global }];
if (h.length === 1) items.push({ tipo: 'historico', id: String(h[0].id), name: rc.nombre_historico });
if (r.length === 1) items.push({ tipo: 'revision', id: String(r[0].id), name: rc.nombre_revision });
return items.map(function (it) {
  return { json: Object.assign({ ruta_destino: rc.dir_entrada + '/' + it.name, historico_en_drive: h.length === 1, revision_en_drive: r.length === 1 }, it) };
});

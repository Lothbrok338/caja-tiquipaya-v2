// Guardia de cierre: historico maestro de CONTROL 1 en la raiz de 05_CONTROLES. 0 = nunca se ha cerrado nada
// (GLOBAL regenerable); 1 = se descarga para que Python decida si ESTE periodo ya esta cerrado; >1 = ambiguo.
const r = $('RESOLVER carpeta SAP oficial').first().json;
const hist = $('BUSCAR historico CONTROL1 (guardia de cierre)').all()
  .map(function (i) { return i.json; })
  .filter(function (j) { return j && j.id && j.name === r.nombre_historico; });
if (hist.length > 1) {
  throw new Error('ERROR_AMBIGUO_HISTORICO: hay ' + hist.length + ' archivos "' + r.nombre_historico + '" en 05_CONTROLES. No se elige ninguno.');
}
return [{ json: { hay_historico: hist.length === 1, historico_id: hist.length === 1 ? String(hist[0].id) : null } }];

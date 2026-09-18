// Carpeta del periodo: CONTROL_1_ASIGNACIONES/<YYYY-MM>. 0 = periodo nuevo (sin revision previa); 1 = se usa; >1 = ambiguo.
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
const carpetas = $('BUSCAR carpeta del periodo (Drive)').all()
  .map(function (i) { return i.json; })
  .filter(function (j) { return j && j.id && j.name === rc.periodo; });
if (carpetas.length > 1) {
  throw new Error('ERROR_AMBIGUO_CARPETA_PERIODO: hay ' + carpetas.length + ' carpetas "' + rc.periodo + '" en CONTROL_1_ASIGNACIONES. No se elige ninguna.');
}
return [{ json: { hay_carpeta: carpetas.length === 1, carpeta_id: carpetas.length === 1 ? String(carpetas[0].id) : null } }];

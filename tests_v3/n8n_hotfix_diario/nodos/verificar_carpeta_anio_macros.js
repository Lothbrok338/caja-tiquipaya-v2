// Carpeta del anio dentro de la raiz institucional de MACROS. 0 -> no configurado (falla cerrado, nunca
// se inventa ni se cae a otro anio); >1 -> ambiguo (falla cerrado, nunca se elige el primero).
const rp = $('RESOLVER procesar_entrada (MACROS y cierres)').first().json;
const anios = $('BUSCAR - Carpeta anio MACROS (Drive)').all()
  .map(function (i) { return i.json; })
  .filter(function (j) { return j && j.id && j.name === rp.anio; });
if (anios.length > 1) {
  return [{ json: { hay_error: true, mensaje_error: 'ERROR_AMBIGUO_CARPETA_ANIO_MACROS: hay ' + anios.length + ' carpetas "' + rp.anio + '" en la carpeta raiz de MACROS. No se elige ninguna: deje una sola y vuelva a procesar.' } }];
}
if (anios.length === 0) {
  return [{ json: { hay_error: true, mensaje_error: 'MACROS_CARPETA_ANIO_NO_ENCONTRADA: no existe la carpeta "' + rp.anio + '" en la carpeta raiz de MACROS en Drive. Procesar no usa una copia local como sustituto.' } }];
}
return [{ json: { hay_error: false, carpeta_anio_id: String(anios[0].id) } }];

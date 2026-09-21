// Carpeta del periodo (YYYY-MM) dentro de la carpeta del anio de MACROS. Si la carpeta del anio ya fallo
// (hay_error), no tiene sentido buscar el mes: se propaga el mismo error tal cual, sin volver a evaluar nada.
const rpAnio = $('VERIFICAR - Carpeta anio MACROS').first().json;
if (rpAnio.hay_error) {
  return [{ json: rpAnio }];
}
const rp = $('RESOLVER procesar_entrada (MACROS y cierres)').first().json;
const meses = $('BUSCAR - Carpeta mes MACROS (Drive)').all()
  .map(function (i) { return i.json; })
  .filter(function (j) { return j && j.id && j.name === rp.periodo; });
if (meses.length > 1) {
  return [{ json: { hay_error: true, mensaje_error: 'ERROR_AMBIGUO_CARPETA_MES_MACROS: hay ' + meses.length + ' carpetas "' + rp.periodo + '" dentro de "' + rp.anio + '". No se elige ninguna: deje una sola y vuelva a procesar.' } }];
}
if (meses.length === 0) {
  return [{ json: { hay_error: true, mensaje_error: 'MACROS_OFICIAL_NO_CONFIGURADO: no hay una carpeta de MACROS oficial de Drive configurada para el periodo ' + rp.periodo + '. Procesar no usa una copia local como sustituto.' } }];
}
return [{ json: { hay_error: false, carpeta_mes_id: String(meses[0].id) } }];

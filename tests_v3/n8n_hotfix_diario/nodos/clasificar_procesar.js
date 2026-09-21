// MACROS oficial: EXACTAMENTE un archivo cuyo nombre empiece con "MACROS" (.xlsm o .xlsx) dentro de la carpeta
// del periodo ya resuelta (0 -> error explicito, >1 -> ERROR_AMBIGUO_MACROS; nunca se elige uno arbitrariamente,
// nunca se asume un nombre exacto fijo: el MACROS de agosto se llamaba distinto al de septiembre en Drive real).
// Si la carpeta del anio o del mes ya fallo (hay_error), se propaga ese mismo error sin tocar Drive de nuevo.
// Cierres: cada ENCONTRADO por la ingesta se descarga por su drive_file_id (identidad exacta ya resuelta), con el
// nombre esperado. Los errores no lanzan: salen como un item hay_error para que el lote quede en ERROR con un
// mensaje funcional (la interfaz no espera indefinidamente).
const rpMes = $('VERIFICAR - Carpeta mes MACROS').first().json;
if (rpMes.hay_error) {
  return [{ json: { hay_error: true, mensaje_error: rpMes.mensaje_error } }];
}
const rp = $('RESOLVER procesar_entrada (MACROS y cierres)').first().json;
const candidatos = $('BUSCAR MACROS oficial (Drive)').all()
  .map(function (i) { return i.json; })
  .filter(function (j) { return j && j.id && typeof j.name === 'string' && j.name.indexOf('MACROS') === 0 && (j.name.slice(-5) === '.xlsm' || j.name.slice(-5) === '.xlsx'); });
if (candidatos.length === 0) {
  return [{ json: { hay_error: true, mensaje_error: 'MACROS_OFICIAL_NO_ENCONTRADO: no existe ningun archivo "MACROS*.xlsm/.xlsx" en la carpeta oficial de MACROS del periodo ' + rp.periodo + ' en Drive. Procesar no usa una copia local como sustituto.' } }];
}
if (candidatos.length > 1) {
  return [{ json: { hay_error: true, mensaje_error: 'ERROR_AMBIGUO_MACROS: hay ' + candidatos.length + ' archivos "MACROS*" en la carpeta oficial de MACROS del periodo ' + rp.periodo + '. No se elige ninguno: deje uno solo y vuelva a procesar.' } }];
}
const macrosNombre = candidatos[0].name;
const ingesta = (($('EJECUTAR - 01 INGESTA (Drive real)').first().json.data || {}).cierres) || [];
const vistos = {};
const items = [{ tipo: 'macros', id: String(candidatos[0].id), name: macrosNombre, ruta_destino: rp.dir_entrada + '/' + macrosNombre }];
ingesta.forEach(function (c) {
  if (c && c.estado_ingesta === 'ENCONTRADO' && c.drive_file_id && c.archivo_esperado && !vistos[c.drive_file_id]) {
    vistos[c.drive_file_id] = true;
    items.push({ tipo: 'cierre', id: String(c.drive_file_id), name: c.archivo_esperado, ruta_destino: rp.dir_cierres + '/' + c.archivo_esperado });
  }
});
return items.map(function (it) { return { json: Object.assign({ hay_error: false }, it) }; });

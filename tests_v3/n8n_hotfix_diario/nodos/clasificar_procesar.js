// MACROS oficial: EXACTAMENTE un archivo con el nombre configurado en la carpeta oficial (0 -> error explicito,
// >1 -> ERROR_AMBIGUO_MACROS; nunca se elige uno arbitrariamente). Cierres: cada ENCONTRADO por la ingesta se descarga
// por su drive_file_id (identidad exacta ya resuelta), con el nombre esperado. Los errores no lanzan: salen como un item
// hay_error para que el lote quede en ERROR con un mensaje funcional (la interfaz no espera indefinidamente).
const rp = $('RESOLVER procesar_entrada (MACROS y cierres)').first().json;
if (!rp.macros_configurado) {
  return [{ json: { hay_error: true, mensaje_error: 'MACROS_OFICIAL_NO_CONFIGURADO: no hay un MACROS oficial de Drive configurado para el periodo ' + rp.periodo + '. Procesar no usa una copia local como sustituto.' } }];
}
const macros = $('BUSCAR MACROS oficial (Drive)').all()
  .map(function (i) { return i.json; })
  .filter(function (j) { return j && j.id && j.name === rp.macros_nombre; });
if (macros.length === 0) {
  return [{ json: { hay_error: true, mensaje_error: 'MACROS_OFICIAL_NO_ENCONTRADO: no existe "' + rp.macros_nombre + '" en la carpeta oficial de MACROS en Drive. Procesar no usa una copia local como sustituto.' } }];
}
if (macros.length > 1) {
  return [{ json: { hay_error: true, mensaje_error: 'ERROR_AMBIGUO_MACROS: hay ' + macros.length + ' archivos "' + rp.macros_nombre + '" en la carpeta oficial de MACROS. No se elige ninguno: deje uno solo y vuelva a procesar.' } }];
}
const ingesta = (($('EJECUTAR - 01 INGESTA (Drive real)').first().json.data || {}).cierres) || [];
const vistos = {};
const items = [{ tipo: 'macros', id: String(macros[0].id), name: rp.macros_nombre, ruta_destino: rp.dir_entrada + '/' + rp.macros_nombre }];
ingesta.forEach(function (c) {
  if (c && c.estado_ingesta === 'ENCONTRADO' && c.drive_file_id && c.archivo_esperado && !vistos[c.drive_file_id]) {
    vistos[c.drive_file_id] = true;
    items.push({ tipo: 'cierre', id: String(c.drive_file_id), name: c.archivo_esperado, ruta_destino: rp.dir_cierres + '/' + c.archivo_esperado });
  }
});
return items.map(function (it) { return { json: Object.assign({ hay_error: false }, it) }; });

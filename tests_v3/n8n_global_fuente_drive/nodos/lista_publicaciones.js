// Destinos de publicacion del GLOBAL mensual (SAP_GLOBAL + RESULTADO_GLOBAL).
// - Carpeta INSTITUCIONAL 05_CONTROLES/GLOBAL ($json.carpeta_id, de 07E) para
//   AMBAS cajas: CONTROL 1 / CONTROL 3 institucionales leen SAP_GLOBAL_TIQ/AME
//   solo de ahi. TIQUIPAYA: exactamente el destino historico, nada mas.
// - AMERICA ademas publica en su carpeta propia CAJA AMERICA/GLOBAL (env
//   DRIVE_GLOBAL_AME, SIN default: falla cerrado si no esta configurada).
// Nunca publica un archivo cuyo prefijo no corresponda a la caja del request.
const d = $('DECIDIR - Publicar GLOBAL oficial').item.json;
const caja = String($('RESOLVER carpeta SAP oficial').first().json.caja || '').trim().toLowerCase();
const PREFIJOS = { tiquipaya: 'TIQ', america: 'AME' };
const prefijo = PREFIJOS[caja];
if (!prefijo) {
  throw new Error('CAJA_DESCONOCIDA: "' + caja + '". Cajas validas: america, tiquipaya.');
}
const nombreSap = String(d.ruta_sap || '').split('/').pop();
const nombreResultado = String(d.ruta_resultado || '').split('/').pop();
if (nombreSap.indexOf('SAP_GLOBAL_' + prefijo + '_') !== 0 || nombreResultado.indexOf('RESULTADO_GLOBAL_' + prefijo + '_') !== 0) {
  throw new Error('GLOBAL_NOMBRE_NO_CORRESPONDE_A_CAJA: caja=' + caja + ', archivos=' + nombreSap + ', ' + nombreResultado + '. No se publica nada.');
}
const carpetas = [$json.carpeta_id];
if (caja === 'america') {
  const carpetaAme = String($env.DRIVE_GLOBAL_AME || '').trim();
  if (!carpetaAme) {
    throw new Error('DRIVE_AME_PENDIENTE: falta configurar DRIVE_GLOBAL_AME (carpeta "CAJA AMERICA/GLOBAL"). No se publica nada.');
  }
  if (carpetas.indexOf(carpetaAme) === -1) carpetas.push(carpetaAme);
}
const items = [];
carpetas.forEach(function (carpetaId) {
  items.push({ json: { carpeta_id: carpetaId, nombre_archivo: nombreSap, ruta_local_origen: d.ruta_sap, modo_si_existe: 'actualizar' } });
  items.push({ json: { carpeta_id: carpetaId, nombre_archivo: nombreResultado, ruta_local_origen: d.ruta_resultado, modo_si_existe: 'actualizar' } });
});
return items;

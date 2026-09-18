// Estructura en Drive: historico CANONICO en la raiz de 05_CONTROLES; artefactos del periodo en
// CONTROL_1_ASIGNACIONES/<YYYY-MM>/ (carpeta buscada-o-creada por 07E justo antes de este nodo).
// Orden deliberado: GLOBAL corregido -> revision -> detalle -> snapshot del historico (evidencia del periodo)
// -> historico MAESTRO de la raiz SIEMPRE al final: si algo falla antes, la fuente canonica nunca queda
// adelantada respecto de lo que se publico.
const d = $('DECIDIR - Publicar CONTROL1 oficial').first().json;
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
const carpetaPeriodo = $('EJECUTAR 07E carpeta del periodo CONTROL1').first().json.carpeta_id;
if (!carpetaPeriodo) { throw new Error('CARPETA_PERIODO_CONTROL1_NO_RESUELTA: 07E no devolvio carpeta_id para ' + rc.periodo); }
const items = [];
if (d.publicar_global) {
  items.push({ carpeta_id: rc.carpeta_global_id, nombre_archivo: rc.nombre_global, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_global, modo_si_existe: 'actualizar' });
}
if (d.hay_revision) {
  items.push({ carpeta_id: carpetaPeriodo, nombre_archivo: rc.nombre_revision, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_revision, modo_si_existe: 'actualizar' });
}
if (d.hay_detalle) {
  items.push({ carpeta_id: carpetaPeriodo, nombre_archivo: rc.nombre_detalle, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_detalle, modo_si_existe: 'actualizar' });
}
if (d.hay_historico) {
  items.push({ carpeta_id: carpetaPeriodo, nombre_archivo: rc.nombre_historico, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_historico, modo_si_existe: 'actualizar' });
  items.push({ carpeta_id: rc.carpeta_controles_id, nombre_archivo: rc.nombre_historico, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_historico, modo_si_existe: 'actualizar' });
}
return items.map(function (it) { return { json: it }; });

// Orden deliberado: GLOBAL corregido -> revision -> historico (el historico va SIEMPRE al final: si algo
// falla antes, Drive nunca queda con un historico que dice "GLOBAL final X" y un GLOBAL distinto).
const d = $json;
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
const items = [];
if (d.publicar_global) {
  items.push({ carpeta_id: rc.carpeta_global_id, nombre_archivo: rc.nombre_global, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_global, modo_si_existe: 'actualizar' });
}
if (d.hay_revision) {
  items.push({ carpeta_id: rc.carpeta_control1_id, nombre_archivo: rc.nombre_revision, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_revision, modo_si_existe: 'actualizar' });
}
if (d.hay_historico) {
  items.push({ carpeta_id: rc.carpeta_controles_id, nombre_archivo: rc.nombre_historico, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_historico, modo_si_existe: 'actualizar' });
}
return items.map(function (it) { return { json: it }; });

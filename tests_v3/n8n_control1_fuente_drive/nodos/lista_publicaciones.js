// Estructura en Drive: historico institucional CANONICO en la raiz de
// 05_CONTROLES; artefactos del periodo (detalle + estado sellado) en
// CONTROL_1_ASIGNACIONES/<YYYY-MM>/ (carpeta buscada-o-creada por 07E justo
// antes de este nodo). Orden deliberado: detalle -> estado del periodo ->
// snapshot del historico (evidencia del periodo) -> historico MAESTRO de la
// raiz SIEMPRE al final: si algo falla antes, la fuente canonica nunca queda
// adelantada respecto de lo que se publico. CONTROL 1 institucional nunca
// publica un GLOBAL aqui (ver DECIDIR - Publicar CONTROL1 oficial).
const d = $('DECIDIR - Publicar CONTROL1 oficial').first().json;
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
const carpetaPeriodo = $('EJECUTAR 07E carpeta del periodo CONTROL1').first().json.carpeta_id;
if (!carpetaPeriodo) { throw new Error('CARPETA_PERIODO_CONTROL1_NO_RESUELTA: 07E no devolvio carpeta_id para ' + rc.periodo); }
const items = [];
if (d.hay_detalle) {
  items.push({ carpeta_id: carpetaPeriodo, nombre_archivo: rc.nombre_detalle, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_detalle, modo_si_existe: 'actualizar' });
}
if (d.hay_estado) {
  items.push({ carpeta_id: carpetaPeriodo, nombre_archivo: rc.nombre_estado, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_estado, modo_si_existe: 'actualizar' });
}
if (d.hay_historico) {
  items.push({ carpeta_id: carpetaPeriodo, nombre_archivo: rc.nombre_historico, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_historico, modo_si_existe: 'actualizar' });
  items.push({ carpeta_id: rc.carpeta_controles_id, nombre_archivo: rc.nombre_historico, ruta_local_origen: rc.dir_entrada + '/' + rc.nombre_historico, modo_si_existe: 'actualizar' });
}
return items.map(function (it) { return { json: it }; });

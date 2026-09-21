// Estructura en Drive: historico CANONICO en la raiz de 05_CONTROLES; artefactos del periodo en
// CONTROL_1_ASIGNACIONES/<YYYY-MM>/ (carpeta buscada-o-creada por 07E justo antes de este nodo).
// Orden deliberado: GLOBAL(s) corregidos (TIQ, luego AME, cada uno solo si esa caja realmente
// cambio) -> detalle/revision del periodo -> snapshot del historico (evidencia del periodo) ->
// historico MAESTRO de la raiz SIEMPRE al final: si algo falla antes, la fuente canonica nunca
// queda adelantada respecto de lo que se publico. Nunca hay un tercer GLOBAL combinado.
const d = $('DECIDIR - Publicar CONTROL1 oficial').first().json;
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;
const carpetaPeriodo = $('EJECUTAR 07E carpeta del periodo CONTROL1').first().json.carpeta_id;
if (!carpetaPeriodo) { throw new Error('CARPETA_PERIODO_CONTROL1_NO_RESUELTA: 07E no devolvio carpeta_id para ' + rc.periodo); }
const p = function (carpeta, nombre) { return { carpeta_id: carpeta, nombre_archivo: nombre, ruta_local_origen: rc.dir_entrada + '/' + nombre, modo_si_existe: 'actualizar' }; };
const items = [];
if (d.publicar_global_tiq) items.push(p(rc.carpeta_global_id, rc.nombre_global_tiq));
if (d.publicar_global_ame) items.push(p(rc.carpeta_global_id, rc.nombre_global_ame));
if (d.hay_detalle) items.push(p(carpetaPeriodo, rc.nombre_detalle));
if (d.hay_historico) {
  items.push(p(carpetaPeriodo, rc.nombre_historico));
  items.push(p(rc.carpeta_controles_id, rc.nombre_historico));
}
return items.map(function (it) { return { json: it }; });

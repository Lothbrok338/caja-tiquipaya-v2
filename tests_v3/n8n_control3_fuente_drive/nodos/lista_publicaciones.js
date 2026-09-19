// Estructura en Drive: historicos MAESTROS en la raiz de 05_CONTROLES; artefactos del periodo en
// CONTROL_3_CXC_CXP/<YYYY-MM>/ (carpeta buscada-o-creada por 07E justo antes de este nodo).
// Orden deliberado: reporte -> json -> snapshots del periodo (evidencia) -> historico MAESTRO -> libro de periodos
// MAESTRO SIEMPRE al final: si algo falla antes, la fuente canonica nunca queda adelantada respecto de lo publicado
// (y si falla justo entre el historico y el libro, el siguiente cierre lo recupera sin reacumular).
const d = $('DECIDIR - Publicar CONTROL3 oficial').first().json;
const rc = $('RESOLVER control3 (periodo y carpetas)').first().json;
const carpetaPeriodo = $('EJECUTAR 07E carpeta del periodo CONTROL3').first().json.carpeta_id;
if (!carpetaPeriodo) { throw new Error('CARPETA_PERIODO_CONTROL3_NO_RESUELTA: 07E no devolvio carpeta_id para ' + rc.periodo); }
const items = [];
const p = function (carpeta, nombre) { return { carpeta_id: carpeta, nombre_archivo: nombre, ruta_local_origen: rc.dir_entrada + '/' + nombre, modo_si_existe: 'actualizar' }; };
if (d.hay_reporte) items.push(p(carpetaPeriodo, rc.nombre_reporte));
if (d.hay_reporte_json) items.push(p(carpetaPeriodo, rc.nombre_reporte_json));
if (d.hay_snapshots) {
  items.push(p(carpetaPeriodo, rc.nombre_historico));
  items.push(p(carpetaPeriodo, rc.nombre_periodos));
}
if (d.hay_historico) items.push(p(rc.carpeta_controles_id, rc.nombre_historico));
if (d.hay_periodos) items.push(p(rc.carpeta_controles_id, rc.nombre_periodos));
return items.map(function (it) { return { json: it }; });

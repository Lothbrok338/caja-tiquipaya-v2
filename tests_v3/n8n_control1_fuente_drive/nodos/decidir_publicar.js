const modo = (($('WEBHOOK control1').first().json.body) || {}).modo || 'dev';
const r = $json.data || {};
if (modo !== 'official') {
  return [{ json: { debe_publicar: false, hay_detalle: false, hay_historico: false, hay_estado: false, publicar_global: false } }];
}
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;

// Detalle (revision institucional del periodo): se publica siempre que esta
// corrida haya escrito su propio ruta_detalle_json para el periodo pedido.
const hayDetalle = typeof r.ruta_detalle_json === 'string' && r.ruta_detalle_json.split('/').pop() === rc.nombre_detalle;
// PRELIMINAR (mes abierto): solo el detalle del periodo. El historico
// institucional y el estado sellado solo se publican tras un CIERRE
// DEFINITIVO explicito (modo_control1='cerrar').
const esCierre = r.modo_control1 === 'cerrar';
const hayHistorico = esCierre && r.historico_actualizado === true;
const hayEstado = hayHistorico; // el estado se sella en el MISMO cierre que el historico.
// La correccion del GLOBAL de origen (corregir_control1_institucional) viaja
// en una accion separada y atomica entre TIQ/AME; este endpoint nunca la
// ejecuta, asi que nunca publica un GLOBAL corregido.
const publicarGlobal = false;

return [{ json: { debe_publicar: hayDetalle || hayHistorico || hayEstado, hay_detalle: hayDetalle, hay_historico: hayHistorico, hay_estado: hayEstado, publicar_global: publicarGlobal } }];

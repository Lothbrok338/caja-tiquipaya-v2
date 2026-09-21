// FASE 12F -- CONTROL 1 institucional: ya no hay UN GLOBAL por caja ni una
// REVISION_ASIGNACIONES por-caja (ver clasificar.js). El resultado que llega
// aqui es el de v3.control1_institucional.ejecutar_control1_institucional
// (mezclado con {resultado, dir_entrada, modo} por v3/dev_api.py):
//   estado, periodo, sha_par, archivo_global_tiq, archivo_global_ame,
//   candidatas_tiq/ame, alertas, dry_run, historico_actualizado,
//   ruta_detalle_json (solo si CONTROL1 lo escribio en esta corrida), modo.
// Las correcciones autorizadas (si las hubo) se aplican ANTES de este paso
// (ver construir_payload.js) y tocan CADA GLOBAL de su caja de origen por
// separado: nunca existe un tercer GLOBAL combinado que publicar.
const modo = (($('WEBHOOK control1').first().json.body) || {}).modo || 'dev';
const vacio = { debe_publicar: false, hay_detalle: false, hay_historico: false, publicar_global_tiq: false, publicar_global_ame: false };
if (modo !== 'official') {
  return [{ json: vacio }];
}
const body = ($('WEBHOOK control1').first().json.body) || {};
const r = $json.data || {};
if (r.resultado === 'ERROR' || r.estado === 'ERROR_TECNICO') {
  return [{ json: vacio }];
}
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;

// Detalle/revision institucional del periodo: solo si CONTROL1 lo escribio en ESTA corrida
// (mismo nombre canonico del periodo pedido).
const hayDetalle = typeof r.ruta_detalle_json === 'string' && r.ruta_detalle_json.split('/').pop() === rc.nombre_detalle;

// CIERRE DEFINITIVO explicito (confirmacion_cierre=true) Y exitoso (persistio el historico
// institucional en ESTA corrida, sin duplicados pendientes). PRELIMINAR (mes abierto) nunca
// llega aqui con historico_actualizado=true: dev_api fuerza dry_run=True sin confirmacion_cierre.
const esCierre = r.modo === 'cierre' && r.historico_actualizado === true;
const hayHistorico = esCierre;

// GLOBAL corregido: solo si hubo correcciones autorizadas para ESA caja Y el cierre fue exitoso.
// Cada caja se publica de forma independiente (si solo cambio AME, TIQ nunca se publica). Nunca
// se fusionan en un tercer GLOBAL: son dos archivos, dos decisiones.
const correccionesTiq = Array.isArray(body.correcciones_tiq) ? body.correcciones_tiq : [];
const correccionesAme = Array.isArray(body.correcciones_ame) ? body.correcciones_ame : [];
const publicarGlobalTiq = esCierre && correccionesTiq.length > 0;
const publicarGlobalAme = esCierre && correccionesAme.length > 0;

return [{
  json: {
    debe_publicar: hayDetalle || hayHistorico || publicarGlobalTiq || publicarGlobalAme,
    hay_detalle: hayDetalle,
    hay_historico: hayHistorico,
    publicar_global_tiq: publicarGlobalTiq,
    publicar_global_ame: publicarGlobalAme,
  },
}];

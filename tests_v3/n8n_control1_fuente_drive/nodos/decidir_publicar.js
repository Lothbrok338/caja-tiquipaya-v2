const modo = (($('WEBHOOK control1').first().json.body) || {}).modo || 'dev';
const r = $json.data || {};
if (modo !== 'official') {
  return [{ json: { debe_publicar: false, hay_revision: false, hay_detalle: false, hay_historico: false, publicar_global: false, ruta_revision: null } }];
}
const rc = $('RESOLVER control1 (periodo y carpetas)').first().json;

// Revision, detalle e historico: solo cuando la logica de CONTROL 1 los escribio en ESTA corrida.
const hayRevision = r.revision_actualizada === true && typeof r.ruta_revision === 'string' && r.ruta_revision.split('/').pop() === rc.nombre_revision;
const hayDetalle = typeof r.detalle_json === 'string' && r.detalle_json.split('/').pop() === rc.nombre_detalle;
const hayHistorico = r.historico_actualizado === true;

// GLOBAL corregido: solo si CONTROL 1 realmente lo modifico como resultado autorizado
// (validacion del auditor cerrada), es el MISMO GLOBAL oficial descargado en esta corrida
// (mismo nombre/periodo, SHA original distinto del final) y no es simulacro.
const publicarGlobal = r.global_modificado === true
  && r.estado_validacion === 'CERRADO_CON_VALIDACION_AUDITOR'
  && Number(r.correcciones_aplicadas) > 0
  && r.dry_run !== true
  && r.archivo_global === rc.nombre_global
  && r.periodo === (rc.mes_nombre + '_' + rc.anio)
  && typeof r.sha256_global_original === 'string' && typeof r.sha256_global_final === 'string'
  && r.sha256_global_original !== r.sha256_global_final;

return [{ json: { debe_publicar: hayRevision || hayDetalle || hayHistorico || publicarGlobal, hay_revision: hayRevision, hay_detalle: hayDetalle, hay_historico: hayHistorico, publicar_global: publicarGlobal, ruta_revision: hayRevision ? r.ruta_revision : null } }];

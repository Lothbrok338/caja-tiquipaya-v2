// FASE 12F -- CONTROL 3 institucional: el resultado que llega aqui es el de
// v3.control3_institucional.ejecutar_control3_institucional (mezclado con
// {resultado, dir_entrada, modo} por v3/dev_api.py):
//   estado ('OK' | 'YA_PROCESADO_SIN_CAMBIOS' | 'GLOBAL_MODIFICADO_REQUIERE_REVISION'
//   | 'ERROR_TECNICO'), periodo, sha_par, archivo_global_tiq/ame, dry_run,
//   historico_actualizado, archivo_control_xlsx, archivo_control_json, modo
//   ('preliminar' | 'cierre'). Nunca modifica ningun GLOBAL: CONTROL 3 es
//   solo lectura, no hay GLOBAL que publicar aqui.
const modo = (($('WEBHOOK control3').first().json.body) || {}).modo || 'dev';
const vacio = { debe_publicar: false, hay_reporte: false, hay_reporte_json: false, hay_snapshots: false, hay_historico: false, hay_periodos: false };
if (modo !== 'official') {
  return [{ json: vacio }];
}
const r = $json.data || {};
if (r.resultado === 'ERROR' || r.estado === 'ERROR_TECNICO') {
  return [{ json: vacio }];
}
const rc = $('RESOLVER control3 (periodo y carpetas)').first().json;

// Reporte (xlsx + json) del periodo: solo si CONTROL 3 lo escribio en ESTA corrida, con el nombre canonico del periodo.
const nombreDe = function (ruta) { return typeof ruta === 'string' ? ruta.split('/').pop() : null; };
const hayReporte = nombreDe(r.archivo_control_xlsx) === rc.nombre_reporte;
const hayReporteJson = nombreDe(r.archivo_control_json) === rc.nombre_reporte_json;

// CIERRE DEFINITIVO explicito (confirmacion_cierre=true) Y exitoso (sello el periodo, persistio
// los historicos MAESTROS en ESTA corrida). PRELIMINAR (mes abierto) nunca llega aqui con
// historico_actualizado=true: dev_api fuerza dry_run=True sin confirmacion_cierre.
const cerro = r.modo === 'cierre' && r.historico_actualizado === true;
const hayHistorico = cerro;
const hayPeriodos = cerro;
const haySnapshots = cerro;

return [{ json: { debe_publicar: hayReporte || hayReporteJson || haySnapshots || hayHistorico || hayPeriodos, hay_reporte: hayReporte, hay_reporte_json: hayReporteJson, hay_snapshots: haySnapshots, hay_historico: hayHistorico, hay_periodos: hayPeriodos } }];

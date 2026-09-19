const modo = (($('WEBHOOK control3').first().json.body) || {}).modo || 'dev';
const r = $json.data || {};
const vacio = { debe_publicar: false, hay_reporte: false, hay_reporte_json: false, hay_snapshots: false, hay_historico: false, hay_periodos: false };
if (modo !== 'official' || r.resultado === 'ERROR' || r.estado === 'ERROR_TECNICO' || r.dry_run === true) {
  return [{ json: vacio }];
}
const rc = $('RESOLVER control3 (periodo y carpetas)').first().json;

// Reporte (xlsx + json) del periodo: solo si CONTROL 3 lo escribio en ESTA corrida, con el nombre canonico del periodo.
const nombreDe = function (ruta) { return typeof ruta === 'string' ? ruta.split('/').pop() : null; };
const hayReporte = nombreDe(r.archivo_control_xlsx) === rc.nombre_reporte;
const hayReporteJson = nombreDe(r.archivo_control_json) === rc.nombre_reporte_json;

// PRELIMINAR (mes abierto): solo artefactos del periodo. Los historicos MAESTROS y los snapshots solo se publican
// tras un CIERRE DEFINITIVO explicito que realmente cerro el periodo en esta corrida.
const cerro = r.modo_control3 === 'cerrar' && r.estado_control3 === 'CERRADO';
const hayHistorico = cerro && r.historico_actualizado === true;
const hayPeriodos = cerro && r.periodos_actualizado === true;
const haySnapshots = cerro;

return [{ json: { debe_publicar: hayReporte || hayReporteJson || haySnapshots || hayHistorico || hayPeriodos, hay_reporte: hayReporte, hay_reporte_json: hayReporteJson, hay_snapshots: haySnapshots, hay_historico: hayHistorico, hay_periodos: hayPeriodos } }];

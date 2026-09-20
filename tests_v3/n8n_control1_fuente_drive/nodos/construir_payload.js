const t = $('WEBHOOK control1').first().json;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());

// Payload para v3.dev_api (ejecutar_control1) -- Python es la unica
// autoridad. Opera sobre el GLOBAL OFICIAL que este backend acaba de
// descargar de Drive a control1_entrada/<periodo>/ (nunca sobre un GLOBAL
// local). Cero logica contable aqui.
// MODO: PRELIMINAR (mes abierto) por defecto; el cierre definitivo solo viaja
// si el frontend envia modo_control1='cerrar' Y confirmacion_cierre=true (tras
// la confirmacion humana). Aqui NUNCA se infiere el cierre.
const payload = { anio: t.body.anio, mes: t.body.mes, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir', ruta_revision_json: t.body.ruta_revision_json || null, dry_run: t.body.dry_run || false, modo_control1: t.body.modo_control1 || 'preliminar', confirmacion_cierre: t.body.confirmacion_cierre === true, caja: t.body.caja || 'tiquipaya' };

const rutaInputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_control1_input_' + executionId + '.json';
const rutaOutputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_control1_output_' + executionId + '.json';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
  },
}];

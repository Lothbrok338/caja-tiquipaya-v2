const t = $('WEBHOOK control3').first().json;
const body = t.body || {};
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());

// CONTROL 3 institucional (un solo boton, no depende del selector de caja):
// PRELIMINAR (por defecto) nunca toca ningun historico. CIERRE (sella el
// periodo: actualiza HISTORICO_CXC_CXP.csv + su libro de periodos) solo
// viaja si el frontend envia confirmacion_cierre=true explicito (tras
// confirmacion humana) -- aqui NUNCA se infiere el cierre. `caja` NUNCA se
// lee del body: CONTROL 3 institucional no tiene (ni necesita) fallback a
// 'tiquipaya'. CONTROL 3 nunca modifica ningun GLOBAL.
const payload = { anio: body.anio, mes: body.mes, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir', dry_run: body.dry_run || false, confirmacion_cierre: body.confirmacion_cierre === true };

const rutaInputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_control3_input_' + executionId + '.json';
const rutaOutputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_control3_output_' + executionId + '.json';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
  },
}];
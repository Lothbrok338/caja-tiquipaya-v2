const rp = $('RESOLVER procesar_entrada (MACROS y cierres)').first().json;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const err = $('CLASIFICAR - MACROS y cierres de procesar').first().json;
const payload = { lote_id: rp.lote_id, mensaje: err.mensaje_error, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir' };
return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_marcar_error_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_marcar_error_output_' + executionId + '.json',
  },
}];

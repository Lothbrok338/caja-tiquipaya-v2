// Combina la respuesta local (publicados) con la salida real de 06B (publicados_drive_oficial) y deja que PYTHON decida el
// estado de publicacion: PUBLICADO_OFICIAL solo con 06B PUBLICADO_OFICIAL+publicado=true. Este nodo no decide nada.
const lote = $('WEBHOOK publicar').first().json.body.lote_id;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const payload = { respuesta: $json, lote_id: lote, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir' };
return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_consolidar_publicar_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_consolidar_publicar_output_' + executionId + '.json',
  },
}];

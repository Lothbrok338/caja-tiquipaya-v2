const t = $input.first().json;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());

// Payload para v3.dev_api (publicar) -- Python es la unica autoridad.
// FASE 10D: base_dir_dev apunta al workdir REAL (mismo que procesar_lote).
// HOTFIX 2026-09-19: modo_oficial=true -- el paso local solo PREPARA los archivos que 06B sube a Drive (un marcador local
// residual no corta el flujo ni cuenta como publicacion). El estado PUBLICADO solo lo fija la consolidacion posterior,
// con la confirmacion real de 06B/Drive.
const payload = { lote_id: t.body.lote_id, fechas: t.body.fechas, usuario_auditor: t.body.usuario_auditor || null, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir', modo_oficial: true };

const rutaInputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_publicar_input_' + executionId + '.json';
const rutaOutputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_publicar_output_' + executionId + '.json';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
  },
}];

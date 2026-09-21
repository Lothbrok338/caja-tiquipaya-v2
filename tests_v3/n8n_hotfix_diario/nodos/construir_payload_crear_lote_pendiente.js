const t = $input.first().json;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());

// Payload para v3.dev_api (crear_lote_pendiente) -- Python es la unica autoridad.
// Este nodo NUNCA decide nada de negocio: solo empaqueta lo que ya vino
// del request HTTP (body/query), mas rutas DEV FIJAS del lado servidor
// (el navegador nunca elige un path de archivo -- ver Sticky Note de
// seguridad de este workflow). FASE 10D: base_dir_dev apunta al workdir
// REAL (Drive solo lectura), no al fixture de FASE 9.
//
// FASE CAJA-AMERICA (contrato /procesar): a diferencia del default
// historico de config_cajas.resolver_caja(None) -> TIQUIPAYA (que sigue
// vivo para otras APIs/fixtures legacy que nunca mandan `caja`), la ruta
// HTTP /procesar YA NO admite una caja ausente ni invalida -- si el
// transporte la pierde, NUNCA se asume TIQUIPAYA en silencio: se falla
// cerrado AQUI, antes de crear el lote y antes de invocar Python.
const caja = String((t.body || {}).caja || '').trim().toLowerCase();
if (caja !== 'tiquipaya' && caja !== 'america') {
  throw new Error('CAJA_REQUERIDA_EN_PROCESAR: "caja" debe ser "tiquipaya" o "america" (recibido: "' + caja + '"). No se crea el lote.');
}

const payload = { fecha_inicio: t.body.fecha_inicio, fecha_fin: t.body.fecha_fin, usuario_auditor: t.body.usuario_auditor || null, caja: caja, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir' };

const rutaInputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_crear_lote_input_' + executionId + '.json';
const rutaOutputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_crear_lote_output_' + executionId + '.json';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
  },
}];

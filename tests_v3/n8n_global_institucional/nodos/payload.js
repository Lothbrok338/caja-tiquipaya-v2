const t = $input.first().json;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());

// Payload para v3.dev_api (generar_global_institucional) -- Python es la unica autoridad.
// GENERAR GLOBAL institucional: UN solo boton, el navegador SOLO envia anio/mes
// (nunca caja -- el mensual institucional ya no depende del selector de caja,
// a diferencia del flujo DIARIO que si sigue enviando caja). base_dir_dev/
// ruta_plantilla_origen son rutas fijas del lado servidor, mismo criterio que
// 'CONSTRUIR payload global'. sap_dir_tiq/sap_dir_ame se omiten a proposito:
// v3.dev_api.generar_global_institucional() los resuelve el mismo default
// (global_entrada/<periodo> / global_entrada/america/<periodo>) que ya usa
// generar_global() por caja, y falla cerrado si alguno de los dos no esta
// materializado.
const payload = { anio: t.body.anio, mes: t.body.mes, base_dir_dev: '' + ($env.TIQ_BASE_DIR || "/home/codespace/.n8n-files") + '/tiq_v3_real_readonly_dev/dev_workdir', ruta_plantilla_origen: '' + ($env.TIQ_PLANTILLA_SAP_MAESTRA || "/app/assets/Plantilla SAP maestra.xlsx") + '' };

const rutaInputTmp = '' + ($env.TIQ_BASE_DIR || "/home/codespace/.n8n-files") + '/tiq_v3_tmp/tiq_v3_dev_api_global_institucional_input_' + executionId + '.json';
const rutaOutputTmp = '' + ($env.TIQ_BASE_DIR || "/home/codespace/.n8n-files") + '/tiq_v3_tmp/tiq_v3_dev_api_global_institucional_output_' + executionId + '.json';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
  },
}];
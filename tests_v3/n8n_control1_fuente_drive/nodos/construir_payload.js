const t = $('WEBHOOK control1').first().json;
const body = t.body || {};
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';

// CONTROL 1 institucional (un solo boton, no depende del selector de caja):
// PRELIMINAR (por defecto) nunca toca historico ni GLOBAL. CIERRE solo viaja
// si el frontend envia confirmacion_cierre=true explicito (tras confirmacion
// humana) -- aqui NUNCA se infiere el cierre. `caja` NUNCA se lee del body:
// CONTROL 1 institucional no tiene (ni necesita) fallback a 'tiquipaya'.
const confirmacionCierre = body.confirmacion_cierre === true;
const correccionesTiq = Array.isArray(body.correcciones_tiq) ? body.correcciones_tiq : [];
const correccionesAme = Array.isArray(body.correcciones_ame) ? body.correcciones_ame : [];
const hayCorrecciones = confirmacionCierre && (correccionesTiq.length > 0 || correccionesAme.length > 0);

const payload = { anio: body.anio, mes: body.mes, base_dir_dev: baseDirDev, dry_run: body.dry_run || false, confirmacion_cierre: confirmacionCierre };
const rutaInputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_control1_input_' + executionId + '.json';
const rutaOutputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_control1_output_' + executionId + '.json';

let comandoCorregir = '';
if (hayCorrecciones) {
  // CIERRE con correcciones autorizadas por el auditor: aplica AMBOS GLOBAL
  // (staging+rollback cross-archivo, ver
  // v3/control1_institucional.aplicar_correcciones_institucional) ANTES de
  // ejecutar_control1_institucional, para que el historico se actualice ya
  // sobre el GLOBAL corregido.
  const payloadCorregir = { anio: body.anio, mes: body.mes, base_dir_dev: baseDirDev, correcciones_tiq: correccionesTiq, correcciones_ame: correccionesAme };
  const rutaCorregirInput = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_corregir_control1_input_' + executionId + '.json';
  const rutaCorregirOutput = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_corregir_control1_output_' + executionId + '.json';
  const corregirB64 = Buffer.from(JSON.stringify(payloadCorregir), 'utf8').toString('base64');
  comandoCorregir = 'printf \'%s\' \'' + corregirB64 + '\' | base64 -d > "' + rutaCorregirInput + '" && ' +
    '/workspaces/.venv-caja/bin/python3 -m v3.dev_api --accion corregir_control1_institucional --input "' + rutaCorregirInput + '" --output "' + rutaCorregirOutput + '" && ' +
    'grep -q \'"resultado": "OK"\' "' + rutaCorregirOutput + '" && ';
}
const comandoEjecutar = 'cd /workspaces/caja-tiquipaya-v2 && ' + comandoCorregir +
  '/workspaces/.venv-caja/bin/python3 -m v3.dev_api --accion ejecutar_control1_institucional --input "' + rutaInputTmp + '" --output "' + rutaOutputTmp + '" ; true';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
    comando_ejecutar: comandoEjecutar,
  },
}];
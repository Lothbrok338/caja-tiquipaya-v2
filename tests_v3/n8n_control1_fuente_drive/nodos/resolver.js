// FASE 12F -- CONTROL 1 es INSTITUCIONAL: revisa conjuntamente TIQUIPAYA +
// AMERICA del periodo. Nunca depende del selector de caja del frontend (el
// body de /control1 no trae `caja`, y este nodo tampoco lo lee): el backend
// resuelve SIEMPRE ambos nombres de GLOBAL (TIQ y AME) y los materializa
// juntos en control1_institucional_entrada/<periodo>/ (ver v3/dev_api.py
// preparar_control1_institucional_entrada / ejecutar_control1_institucional).
const t = $('WEBHOOK control1').first().json;
const body = t.body || {};
const anio = body.anio;
const mes = body.mes;
if (!Number.isInteger(anio) || anio < 2000 || anio > 2100 || !Number.isInteger(mes) || mes < 1 || mes > 12) {
  throw new Error('PERIODO_INVALIDO: anio/mes deben ser enteros validos (recibido anio=' + anio + ', mes=' + mes + ').');
}
const MESES = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'];
const mesNombre = MESES[mes - 1];
const periodo = anio + '-' + String(mes).padStart(2, '0');

// Folder IDs INSTITUCIONALES (05_CONTROLES, 05_CONTROLES/GLOBAL,
// 05_CONTROLES/CONTROL_1_ASIGNACIONES): los MISMOS para TIQUIPAYA y
// AMERICA -- CONTROL 1 es un control unico que audita ambas cajas juntas.
const CARPETAS_INSTITUCIONALES = {
  controles: '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB',
  global: '1KREzDpgptWRwuArA1qYco49rplOEeeNU',
  control1: '1oOcwIgq_9uU9eRLV7z36zBjdBS-hBlRk',
};
function resolverDestino(clave) {
  return CARPETAS_INSTITUCIONALES[clave];
}

const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';
const dirEntrada = baseDirDev + '/control1_institucional_entrada/' + periodo;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const payloadPrep = { anio: anio, mes: mes, base_dir_dev: baseDirDev };

return [{
  json: {
    anio: anio, mes: mes, periodo: periodo, mes_nombre: mesNombre,
    nombre_global_tiq: 'SAP_GLOBAL_TIQ_' + mesNombre + '_' + anio + '.xlsx',
    nombre_global_ame: 'SAP_GLOBAL_AME_' + mesNombre + '_' + anio + '.xlsx',
    nombre_historico: 'HISTORICO_ASIGNACIONES_INSTITUCIONAL.csv',
    // Drive: 05_CONTROLES (historico institucional unico), 05_CONTROLES/GLOBAL (ambos SAP_GLOBAL_TIQ/AME).
    carpeta_controles_id: resolverDestino('controles'),
    carpeta_global_id: resolverDestino('global'),
    carpeta_control1_id: resolverDestino('control1'),
    dir_entrada: dirEntrada,
    input_b64: Buffer.from(JSON.stringify(payloadPrep), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_control1_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_control1_output_' + executionId + '.json',
  },
}];

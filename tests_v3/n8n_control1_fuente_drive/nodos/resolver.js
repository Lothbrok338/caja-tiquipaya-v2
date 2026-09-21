// FASE 12E.4 -- CONTROL 1: Drive oficial = fuente de verdad; local = materializacion temporal de la corrida.
// FASE 12F -- CONTROL 1 es UNICO/INSTITUCIONAL: revisa conjuntamente
// TIQUIPAYA + AMERICA del periodo, asi que sus carpetas (controles/global/
// control1) son las MISMAS para cualquier caja -- no existen
// DRIVE_CONTROLES_AME / DRIVE_GLOBAL_AME / DRIVE_CONTROL1_AME. `caja` solo
// decide el prefijo del nombre del GLOBAL a auditar (mismo patron que
// config_drive_oficial.py).
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

const caja = (body.caja || 'tiquipaya').toString().trim().toLowerCase();
if (caja !== 'tiquipaya' && caja !== 'america') {
  throw new Error('CAJA_DESCONOCIDA: "' + caja + '". Cajas validas: america, tiquipaya.');
}
const prefijoCaja = caja === 'america' ? 'AME' : 'TIQ';

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
const dirEntrada = baseDirDev + '/control1_entrada/' + (caja === 'america' ? 'america/' : '') + periodo;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const payloadPrep = { anio: anio, mes: mes, base_dir_dev: baseDirDev, caja: caja };

return [{
  json: {
    anio: anio, mes: mes, periodo: periodo, mes_nombre: mesNombre, caja: caja,
    nombre_global: 'SAP_GLOBAL_' + prefijoCaja + '_' + mesNombre + '_' + anio + '.xlsx',
    nombre_historico: 'HISTORICO_ASIGNACIONES.csv',
    nombre_revision: 'REVISION_ASIGNACIONES_' + mesNombre + '_' + anio + '.xlsx',
    nombre_detalle: 'CONTROL_ASIGNACIONES_' + mesNombre + '_' + anio + '.json',
    // Drive: 05_CONTROLES (historico CANONICO), 05_CONTROLES/GLOBAL, 05_CONTROLES/CONTROL_1_ASIGNACIONES (contiene una subcarpeta <YYYY-MM> por periodo).
    carpeta_controles_id: resolverDestino('controles'),
    carpeta_global_id: resolverDestino('global'),
    carpeta_control1_id: resolverDestino('control1'),
    dir_entrada: dirEntrada,
    input_b64: Buffer.from(JSON.stringify(payloadPrep), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_control1_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_control1_output_' + executionId + '.json',
  },
}];

// FASE 12E.7 -- CONTROL 3: Drive oficial = fuente de verdad; local = materializacion temporal de la corrida.
// FASE 12F -- CONTROL 3 es UNICO/INSTITUCIONAL: revisa conjuntamente
// TIQUIPAYA + AMERICA del periodo, asi que sus carpetas (controles/global/
// control3) son las MISMAS para cualquier caja -- no existen
// DRIVE_CONTROLES_AME / DRIVE_GLOBAL_AME / DRIVE_CONTROL3_AME. `caja` solo
// decide el prefijo del nombre del GLOBAL a auditar (mismo patron que
// config_drive_oficial.py).
const t = $('WEBHOOK control3').first().json;
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
// 05_CONTROLES/CONTROL_3_CXC_CXP): los MISMOS para TIQUIPAYA y AMERICA --
// CONTROL 3 es un control unico que audita ambas cajas juntas.
const CARPETAS_INSTITUCIONALES = {
  controles: '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB',
  global: '1KREzDpgptWRwuArA1qYco49rplOEeeNU',
  control3: '15IYQDdpyBwrZTNS-qU8VZa47sVz1ziV_',
};
function resolverDestino(clave) {
  return CARPETAS_INSTITUCIONALES[clave];
}

const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';
const dirEntrada = baseDirDev + '/control3_entrada/' + (caja === 'america' ? 'america/' : '') + periodo;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const payloadPrep = { anio: anio, mes: mes, base_dir_dev: baseDirDev, caja: caja };

return [{
  json: {
    anio: anio, mes: mes, periodo: periodo, mes_nombre: mesNombre, caja: caja,
    nombre_global: 'SAP_GLOBAL_' + prefijoCaja + '_' + mesNombre + '_' + anio + '.xlsx',
    nombre_historico: 'HISTORICO_CXC_CXP.csv',
    nombre_periodos: 'HISTORICO_CXC_CXP_PERIODOS.json',
    nombre_reporte: 'CONTROL_CXC_CXP_' + mesNombre + '_' + anio + '.xlsx',
    nombre_reporte_json: 'CONTROL_CXC_CXP_' + mesNombre + '_' + anio + '.json',
    // Drive: 05_CONTROLES (historicos MAESTROS), 05_CONTROLES/GLOBAL, 05_CONTROLES/CONTROL_3_CXC_CXP (una subcarpeta <YYYY-MM> por periodo).
    carpeta_controles_id: resolverDestino('controles'),
    carpeta_global_id: resolverDestino('global'),
    carpeta_control3_id: resolverDestino('control3'),
    dir_entrada: dirEntrada,
    input_b64: Buffer.from(JSON.stringify(payloadPrep), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_control3_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_control3_output_' + executionId + '.json',
  },
}];

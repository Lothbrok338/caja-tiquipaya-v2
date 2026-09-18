// FASE 12E.3 -- fuente real de GLOBAL = carpeta SAP oficial del periodo en Drive.
const t = $('WEBHOOK global').first().json;
const body = t.body || {};
const anio = body.anio;
const mes = body.mes;
if (!Number.isInteger(anio) || anio < 2000 || anio > 2100 || !Number.isInteger(mes) || mes < 1 || mes > 12) {
  throw new Error('PERIODO_INVALIDO: anio/mes deben ser enteros validos (recibido anio=' + anio + ', mes=' + mes + ').');
}
const periodo = anio + '-' + String(mes).padStart(2, '0');

// Carpeta SAP oficial (04_SALIDAS/<anio>/<periodo>/SAP) por periodo. Es configuracion,
// no logica: cada mes nuevo agrega aqui su carpeta. Un periodo sin carpeta configurada
// falla explicito (nunca se cae a estado local).
const CARPETAS_SAP_OFICIALES = { '2026-09': '1mid4gUHnCmZbISlsAYMwWta3RudTSE13' };
const carpetaSapId = CARPETAS_SAP_OFICIALES[periodo];
if (!carpetaSapId) {
  throw new Error('CARPETA_SAP_OFICIAL_NO_CONFIGURADA: no hay carpeta SAP oficial de Drive configurada para el periodo ' + periodo + '.');
}

const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';
const dirEntrada = baseDirDev + '/global_entrada/' + periodo;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const payloadPrep = { anio: anio, mes: mes, base_dir_dev: baseDirDev };

return [{
  json: {
    anio: anio, mes: mes, periodo: periodo,
    carpeta_sap_id: carpetaSapId, dir_entrada: dirEntrada,
    input_b64: Buffer.from(JSON.stringify(payloadPrep), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_global_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_global_output_' + executionId + '.json',
  },
}];

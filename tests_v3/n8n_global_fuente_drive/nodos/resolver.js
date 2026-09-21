// FASE 12E.3 -- fuente real de GLOBAL = carpeta SAP oficial del periodo en Drive.
// FASE 12F -- 'sap' (SAP diario de origen) es por CAJA: mismo patron (env
// DRIVE_SAP_TIQ/AME, fail cerrado para AMERICA) que config_drive_oficial.py
// / "RESOLVER - Destinos Drive por caja" (06B PUBLICACION OFICIAL /
// PREFLIGHT OFICIAL). 'controles' (05_CONTROLES, donde vive el historico
// maestro compartido) es INSTITUCIONAL: la MISMA carpeta para las dos
// cajas.
const t = $('WEBHOOK global').first().json;
const body = t.body || {};
const anio = body.anio;
const mes = body.mes;
if (!Number.isInteger(anio) || anio < 2000 || anio > 2100 || !Number.isInteger(mes) || mes < 1 || mes > 12) {
  throw new Error('PERIODO_INVALIDO: anio/mes deben ser enteros validos (recibido anio=' + anio + ', mes=' + mes + ').');
}
const periodo = anio + '-' + String(mes).padStart(2, '0');

const caja = (body.caja || 'tiquipaya').toString().trim().toLowerCase();
if (caja !== 'tiquipaya' && caja !== 'america') {
  throw new Error('CAJA_DESCONOCIDA: "' + caja + '". Cajas validas: america, tiquipaya.');
}

// Default TIQUIPAYA de 'sap' (04_SALIDAS/SAP): EXACTAMENTE el folder ID
// historico ya en uso. Solo se usa si DRIVE_SAP_TIQ no esta definida.
// AMERICA: SIN default a proposito -- no existe carpeta SAP AME todavia;
// falla cerrado.
const DEFAULTS_TIQ = {
  sap: '1mid4gUHnCmZbISlsAYMwWta3RudTSE13',
};
function resolverDestino(clave) {
  const envVar = 'DRIVE_' + clave.toUpperCase() + '_' + (caja === 'america' ? 'AME' : 'TIQ');
  const valor = $env[envVar];
  if (valor) return valor;
  if (caja === 'tiquipaya') return DEFAULTS_TIQ[clave];
  throw new Error('DRIVE_AME_PENDIENTE: falta configurar ' + envVar + ' (carpeta "' + clave + '" de CAJA AMERICA todavia no existe en Drive).');
}
// 'controles' (05_CONTROLES, historico maestro compartido) es
// INSTITUCIONAL: la MISMA carpeta para las dos cajas, sin variable
// DRIVE_CONTROLES_AME.
const CARPETA_CONTROLES_INSTITUCIONAL = '1yZI_OCuYOAILg8E6uT-bAmkQtW-XB-qB';
const carpetaSapId = resolverDestino('sap');
const carpetaControlesId = CARPETA_CONTROLES_INSTITUCIONAL;

const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';
const dirEntrada = baseDirDev + '/global_entrada/' + (caja === 'america' ? 'america/' : '') + periodo;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const payloadPrep = { anio: anio, mes: mes, base_dir_dev: baseDirDev, caja: caja };

return [{
  json: {
    anio: anio, mes: mes, periodo: periodo, caja: caja,
    carpeta_sap_id: carpetaSapId, dir_entrada: dirEntrada,
    carpeta_controles_id: carpetaControlesId, nombre_historico: 'HISTORICO_ASIGNACIONES.csv',
    input_b64: Buffer.from(JSON.stringify(payloadPrep), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_global_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_global_output_' + executionId + '.json',
  },
}];

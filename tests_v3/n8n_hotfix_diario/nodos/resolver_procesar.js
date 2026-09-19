// HOTFIX 2026-09-19 -- /procesar: Drive = fuente de verdad de MACROS y del cierre. Cada corrida materializa en
// procesar_entrada/<lote_id>/ el MACROS oficial vigente y los cierres exactos que resolvio la ingesta (por drive_file_id).
const lote = $('INTERPRETAR resultado crear_lote_pendiente').first().json.data.lote_id;
const body = $('WEBHOOK procesar').first().json.body || {};
const fechaInicio = String(body.fecha_inicio || '');
const periodo = fechaInicio.slice(0, 7); // YYYY-MM del inicio del rango (mismo criterio que mes_rango de Python)
// MACROS oficial por periodo (identidad exacta: nombre + carpeta de Drive). Es configuracion, no logica: cada mes nuevo
// agrega aqui su archivo. Un periodo sin configurar falla explicito (nunca se cae a una copia local).
const MACROS_OFICIALES = {
  '2026-09': { nombre: 'MACROS SEPTIEMBRE.xlsm', carpeta_id: '1U0HBoAsiDZy8Dqr3zEHa8_YfS5XcoMab' },
};
const cfg = MACROS_OFICIALES[periodo];
const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const dirEntrada = baseDirDev + '/procesar_entrada/' + lote;
return [{
  json: {
    lote_id: lote, periodo: periodo,
    macros_configurado: !!cfg,
    macros_nombre: cfg ? cfg.nombre : null,
    macros_carpeta_id: cfg ? cfg.carpeta_id : null,
    dir_entrada: dirEntrada, dir_cierres: dirEntrada + '/cierres',
    input_b64: Buffer.from(JSON.stringify({ lote_id: lote, base_dir_dev: baseDirDev }), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_procesar_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_procesar_output_' + executionId + '.json',
  },
}];

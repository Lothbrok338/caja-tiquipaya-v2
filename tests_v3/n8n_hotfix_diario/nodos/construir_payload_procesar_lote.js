const t = $input.first().json;
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const rp = $('RESOLVER procesar_entrada (MACROS y cierres)').first().json;

// Payload para v3.dev_api (procesar_lote) -- Python es la unica autoridad.
// FASE 11A.3: requiere_ingesta_drive=true (modo oficial de este despliegue) -- si EJECUTAR - 01 INGESTA (Drive real) no
// entrego drive_file_id para algun cierre ENCONTRADO (o fallo tecnicamente y t.data.cierres nunca llego),
// v3.dev_api.procesar_lote() rechaza el lote ENTERO (IngestaDriveRequeridaError, estado_lote=ERROR) en vez de caer al
// listado local (os.listdir).
// HOTFIX 2026-09-19: el cierre y MACROS ya NO vienen de copias estaticas locales: se descargaron de Drive en ESTA corrida
// a procesar_entrada/<lote_id>/ (cierres por drive_file_id exacto; MACROS oficial vigente por nombre exacto en su carpeta).
// Plantilla y markers siguen viniendo de sus copias de origen (sin cambios).
// v3.precheck_maestro (Python) sigue decidiendo MAESTRO_APTO/BLOQUEADO (cobertura por fecha de cierre Y de depositos)
// antes de invocar el motor; este nodo no reinterpreta esa decision.
// FIX (bug real, primer intento oficial 10/09): el INTERPRETAR del subworkflow 01 INGESTA envuelve su salida bajo .data
// -> se lee t.data.cierres.
const payload = { lote_id: $('INTERPRETAR resultado crear_lote_pendiente').first().json.data.lote_id, base_dir_dev: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir', origen_cierres_dir: rp.dir_cierres, ruta_maestro_origen: rp.dir_entrada + '/' + rp.macros_nombre, ruta_plantilla_origen: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/plantilla_origen/Plantilla SAP maestra.xlsx', markers_origen_dir: '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/markers_origen', ingesta_precomputada: (t && t.data && t.data.cierres) || null, requiere_ingesta_drive: true };

const rutaInputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_procesar_lote_input_' + executionId + '.json';
const rutaOutputTmp = '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_procesar_lote_output_' + executionId + '.json';

return [{
  json: {
    input_b64: Buffer.from(JSON.stringify(payload), 'utf8').toString('base64'),
    ruta_input_tmp: rutaInputTmp,
    ruta_output_tmp: rutaOutputTmp,
  },
}];

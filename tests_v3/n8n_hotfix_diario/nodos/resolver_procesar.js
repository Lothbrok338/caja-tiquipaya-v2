// HOTFIX 2026-09-19 -- /procesar: Drive = fuente de verdad de MACROS y del cierre. Cada corrida materializa en
// procesar_entrada/<lote_id>/ el MACROS oficial vigente y los cierres exactos que resolvio la ingesta (por drive_file_id).
// FASE CAJA-AMERICA: el MACROS ya NO se busca por un mapa MACROS_OFICIALES hardcodeado a un unico periodo (2026-09) --
// eso rompia cualquier mes distinto. La estructura REAL en Drive (carpeta raiz de MACROS, ver DRIVE_MACROS_RAIZ) es
// <raiz>/<YYYY>/<YYYY-MM>/MACROS*.xlsm|xlsx -- este nodo solo calcula el periodo y la carpeta raiz; la carpeta del
// anio, la del mes y el archivo se resuelven mas adelante buscando en Drive en cada nivel (0/>1 = falla cerrado,
// ver "VERIFICAR - Carpeta anio MACROS", "VERIFICAR - Carpeta mes MACROS" y "CLASIFICAR - MACROS y cierres de procesar").
const lote = $('INTERPRETAR resultado crear_lote_pendiente').first().json.data.lote_id;
const body = $('WEBHOOK procesar').first().json.body || {};
const fechaInicio = String(body.fecha_inicio || '');
const periodo = fechaInicio.slice(0, 7); // YYYY-MM del inicio del rango (mismo criterio que mes_rango de Python)
const anio = periodo.slice(0, 4);
// Carpeta INSTITUCIONAL raiz de MACROS (02_MAESTROS): la MISMA para cualquier periodo y cualquier caja -- Python
// filtra TIQ/AME con la columna CAJA de ATC, el MACROS es compartido. Override solo para pruebas/entornos nuevos.
const MACROS_RAIZ_DEFAULT = '1XOlFEKP3nKSvbHCEpk5l8BKWhOMbhMZB';
const macrosRaizId = $env.DRIVE_MACROS_RAIZ || MACROS_RAIZ_DEFAULT;
const baseDirDev = '/home/codespace/.n8n-files/tiq_v3_real_readonly_dev/dev_workdir';
const executionId = ($execution && $execution.id) ? $execution.id : String(Date.now());
const dirEntrada = baseDirDev + '/procesar_entrada/' + lote;
return [{
  json: {
    lote_id: lote, periodo: periodo, anio: anio, macros_raiz_id: macrosRaizId,
    dir_entrada: dirEntrada, dir_cierres: dirEntrada + '/cierres',
    input_b64: Buffer.from(JSON.stringify({ lote_id: lote, base_dir_dev: baseDirDev }), 'utf8').toString('base64'),
    ruta_input_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_procesar_input_' + executionId + '.json',
    ruta_output_tmp: '/home/codespace/.n8n-files/tiq_v3_tmp/tiq_v3_dev_api_prep_procesar_output_' + executionId + '.json',
  },
}];

// FASE CAJA-AMERICA: /procesar debe pedirle a "01 INGESTA" el folder_entrada
// de la CAJA del LOTE (identidad ya persistida por crear_lote_pendiente,
// nunca del request) -- antes este nodo no existia y "EJECUTAR - 01 INGESTA
// (Drive real)" tenia el folder de 00_ENTRADA_CIERRES de TIQUIPAYA fijo,
// asi que un lote de AMERICA leia igual los cierres de TIQUIPAYA. Copia de
// referencia EXACTA del resolverDestino('entrada') del nodo "RESOLVER -
// Destinos Drive por caja" (06B PUBLICACION OFICIAL / PREFLIGHT OFICIAL) y
// de config_drive_oficial.resolver_destinos_drive() en el backend Python --
// misma identidad; mantener las 3 copias sincronizadas.
const caja = ((($('INTERPRETAR resultado crear_lote_pendiente').first().json.data || {}).caja) || 'tiquipaya').toString().trim().toLowerCase();

if (caja !== 'tiquipaya' && caja !== 'america') {
  throw new Error('CAJA_DESCONOCIDA: "' + caja + '". Cajas validas: america, tiquipaya.');
}

// Default TIQUIPAYA: EXACTAMENTE el folder ID historico de 00_ENTRADA_CIERRES
// (idem config_drive_oficial._TIQ_DEFAULTS['entrada']). AMERICA no tiene
// default a proposito -- sin DRIVE_ENTRADA_AME configurada, falla cerrado,
// nunca hereda el folder de TIQUIPAYA.
const DEFAULT_ENTRADA_TIQ = '1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1';
const envVar = 'DRIVE_ENTRADA_' + (caja === 'america' ? 'AME' : 'TIQ');
const valor = $env[envVar];
const folderEntrada = valor || (caja === 'tiquipaya' ? DEFAULT_ENTRADA_TIQ : null);
if (!folderEntrada) {
  throw new Error('DRIVE_AME_PENDIENTE: falta configurar ' + envVar + ' (carpeta "entrada" de CAJA AMERICA todavia no existe en Drive).');
}

return [{ json: { caja: caja, folder_entrada: folderEntrada } }];

// Respuesta final de /publicar: la salida de Python (estados de publicacion consolidados con la evidencia de 06B/Drive).
const r = $input.first().json || {};
let out = null;
try { out = JSON.parse(r.stdout || ''); } catch (e) { out = null; }
if (!out) {
  return [{ json: { resultado: 'ERROR', codigo: 'CONSOLIDACION_PUBLICACION_FALLIDA', mensaje: 'No se pudo confirmar el estado de la publicacion oficial: ' + String(r.stderr || 'sin salida').slice(0, 300) } }];
}
return [{ json: out }];

'use strict';

/**
 * HOOK 1 (crítico) — detección de payload base64 inline.
 *
 * Regla: NUNCA reconstruir/copiar/transcribir binarios pegando base64
 * dentro de un prompt/comando. La biblioteca base64 en sí NO está
 * prohibida: solo el payload largo pegado inline. Por eso el único
 * chequeo real es "¿hay una tira larga de caracteres base64 seguidos?"
 * — cubre por igual Write/Edit (contenido) y Bash (comando), y cubre
 * automáticamente cualquier variante de decodificación (echo | base64
 * -d, printf | base64 --decode, base64.b64decode("..."),
 * [Convert]::FromBase64String("..."), atob("..."), etc.) porque en
 * todas ellas el blob largo viaja inline en el mismo texto.
 *
 * Un uso seguro como `base64 -d archivo.b64 > salida.bin` o
 * `base64.b64decode(data)` con `data` leído de archivo NUNCA contiene
 * ese blob largo en el texto del comando/contenido, así que nunca activa
 * este chequeo.
 */

const THRESHOLD = 512; // umbral prudente: un SHA-256 (64) o un token corto no activa esto.
const RUN_RE = new RegExp('[A-Za-z0-9+/=]{' + THRESHOLD + ',}');

function containsInlineBase64(text) {
  if (!text || typeof text !== 'string') return false;
  if (RUN_RE.test(text)) return true;
  // También cubre un blob "envuelto" en varias líneas (paste con saltos
  // de línea de formato/ancho de columna, no saltos semánticos reales).
  const joined = text.replace(/[\r\n]+/g, '');
  return RUN_RE.test(joined);
}

const BLOCK_MESSAGE =
  'BASE64 INLINE BLOQUEADO.\n' +
  'No reconstruyas binarios pegando/transcribiendo base64.\n' +
  'Usa el archivo binario/materializado directamente o lee/decodifica ' +
  'desde un archivo existente sin insertar el payload en el prompt/comando.';

module.exports = { containsInlineBase64, BLOCK_MESSAGE, THRESHOLD };

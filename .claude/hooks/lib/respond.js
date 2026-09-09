'use strict';

/**
 * Salida estándar de un hook PreToolUse tipo "command". Silencio total
 * en el camino feliz (allow): sin stdout, exit 0, cero overhead visible.
 */

function allow() {
  process.exit(0);
}

function deny(reason) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
  }));
  process.exit(0);
}

function ask(reason) {
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'ask',
      permissionDecisionReason: reason,
    },
  }));
  process.exit(0);
}

/** Lee todo stdin de forma síncrona; nunca lanza (devuelve '' si falla). */
function readStdinSync() {
  try {
    return require('fs').readFileSync(0, 'utf8');
  } catch (e) {
    return '';
  }
}

/** Parsea el JSON de entrada del hook; en caso de error, permite (allow) y termina el proceso. */
function parseHookInput() {
  const raw = readStdinSync();
  try {
    return JSON.parse(raw || '{}');
  } catch (e) {
    allow(); // entrada ilegible: nunca bloquear por un problema del propio hook.
    return {}; // inalcanzable (allow() termina el proceso), solo para el linter.
  }
}

module.exports = { allow, deny, ask, readStdinSync, parseHookInput };

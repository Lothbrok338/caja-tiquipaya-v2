#!/usr/bin/env node
'use strict';

/**
 * PreToolUse — matcher "Bash".
 *
 * HOOK 1 (parcial): bloquea payload base64 inline en el comando.
 * HOOK 4: `git clone` dentro de un checkout ya existente — ASK.
 * HOOK 5: protección de main/push (force push DENY; push normal corre
 *         la suite completa y decide DENY/ASK según el resultado).
 * HOOK 6: comandos destructivos claros (rm -rf del proyecto, git clean
 *         forzado, git reset --hard, Remove-Item -Recurse del proyecto).
 *
 * Camino feliz (nada de esto aplica): sale en silencio y rápido. La
 * suite completa (HOOK 5) SOLO se ejecuta cuando el comando es
 * realmente un push normal a main — nunca en cada Bash.
 */

const path = require('path');
const { spawnSync } = require('child_process');
const { findRepoRoot, getCurrentBranch } = require('./lib/git-utils');
const { containsInlineBase64, BLOCK_MESSAGE } = require('./lib/base64-guard');
const { allow, deny, ask, parseHookInput } = require('./lib/respond');

/** Separa un comando compuesto en sub-comandos por &&, ||, ; y | (heurística
 * simple y suficiente para detectar patrones "claros" — no es un parser de
 * shell completo, ni falta que lo sea para este guardarraíl). */
function splitSubcommands(command) {
  return command.split(/(?:&&|\|\||;|\|)/).map((s) => s.trim()).filter(Boolean);
}

/** Quita envoltorios habituales (sudo, time, nice -n N, exec) del INICIO
 * de un sub-comando antes de decidir con qué binario arranca realmente. */
function stripLeadingWrappers(sub) {
  return sub.replace(/^(?:sudo|time|exec)\s+/i, '').replace(/^nice\s+(?:-n\s*\d+\s+)?/i, '').trim();
}

/** True si el sub-comando (tras quitar envoltorios) ARRANCA con ese patrón.
 * Ancla al inicio a propósito: evita falsos positivos cuando el texto
 * "git reset --hard" o "rm -rf" aparece dentro de un argumento largo
 * (p. ej. un mensaje de commit citado con heredoc), en vez de ser el
 * comando que realmente se va a ejecutar. */
function startsWith(sub, re) {
  return re.test(stripLeadingWrappers(sub));
}

function hasForceRecursiveFlags(text) {
  if (/-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\b/i.test(text)) return true; // -rf/-fr/-Rf/-fR...
  if (/--recursive\b/.test(text) && /--force\b/.test(text)) return true;
  return false;
}

const RM_DANGEROUS_LITERALS = new Set(['.', './', '*', './*', '/', '~', '$HOME', '..']);

function isDangerousRmTarget(token, root) {
  const t = token.trim();
  if (!t) return false;
  if (RM_DANGEROUS_LITERALS.has(t)) return true;
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const expanded = t === '~' ? home : t.startsWith('~/') ? path.join(home, t.slice(2)) : t;
  const resolved = path.resolve(root, expanded);
  if (resolved === root) return true;
  if (resolved === path.dirname(root)) return true; // borraría al padre del proyecto (lo contiene)
  return false;
}

function isDestructiveSubcommand(sub, root) {
  // Todas las comprobaciones anclan al INICIO del sub-comando (ver
  // startsWith): un comando que solo MENCIONA "git reset --hard" o
  // "rm -rf" dentro de un argumento de texto (p. ej. un mensaje de
  // commit) nunca debe bloquearse — solo el comando que de verdad va a
  // ejecutarse.

  // git reset --hard: siempre destructivo, sin matiz de ruta.
  if (startsWith(sub, /^git\s+reset\b/i) && /--hard\b/i.test(sub)) return true;

  // git clean con flag de fuerza (-f, -fd, -fdx, -xfd, --force...).
  if (startsWith(sub, /^git\s+clean\b/i)) {
    const resto = stripLeadingWrappers(sub).replace(/^git\s+clean\b/i, '');
    if (/(^|\s)-[a-zA-Z]*f[a-zA-Z]*\b/.test(resto) || /--force\b/.test(resto)) return true;
  }

  // rm -rf / -fr apuntando a la raíz del proyecto o a una ruta "ancha".
  if (startsWith(sub, /^rm\b/i) && hasForceRecursiveFlags(sub)) {
    const tokens = stripLeadingWrappers(sub).split(/\s+/).filter(Boolean);
    const args = tokens.slice(1).filter((t) => !t.startsWith('-'));
    if (args.some((t) => isDangerousRmTarget(t, root))) return true;
  }

  // PowerShell: Remove-Item ... -Recurse ... apuntando a raíz del proyecto.
  if (startsWith(sub, /^Remove-Item\b/i) && /-Recurse\b/i.test(sub)) {
    const tokens = stripLeadingWrappers(sub).split(/\s+/).filter(Boolean);
    const args = tokens.slice(1).filter((t) => !t.startsWith('-'));
    if (args.some((t) => isDangerousRmTarget(t, root))) return true;
  }

  return false;
}

function runFullTestSuite(root) {
  const intentos = [
    { cmd: 'python3', args: ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'] },
    { cmd: 'python', args: ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'] },
  ];
  for (const intento of intentos) {
    const res = spawnSync(intento.cmd, intento.args, { cwd: root, encoding: 'utf8', timeout: 170000 });
    if (res.error && res.error.code === 'ENOENT') continue; // intérprete no encontrado; probar el siguiente
    const salida = ((res.stdout || '') + (res.stderr || '')).trim();
    const resumen = salida.split('\n').slice(-6).join('\n');
    return { ok: res.status === 0, resumen };
  }
  return { ok: false, resumen: 'No se encontró un intérprete de Python (python3/python) para ejecutar la suite.' };
}

function checkGitPush(sub, repoRoot, cwd) {
  if (!startsWith(sub, /^git\s+push\b/i)) return null;

  const esForzado = /(^|\s)(-f|--force|--force-with-lease)(\s|$)/i.test(sub);
  const mencionaMain = /\bmain\b/.test(sub);
  const ramaActual = repoRoot ? getCurrentBranch(repoRoot) : null;
  // Sin rama explícita en el comando ("git push" / "git push origin"), se
  // empuja la rama actual: si esa rama es main, el push es a main igual.
  const conRemotoYRama = /^git\s+push\b\s+\S+\s+\S+/i.test(stripLeadingWrappers(sub));
  const apuntaAMain = mencionaMain || (!conRemotoYRama && ramaActual === 'main');

  if (!apuntaAMain) return null;

  if (esForzado) {
    return { decision: 'deny', reason: 'Force push a main prohibido por guardarraíl del proyecto.' };
  }

  const resultado = runFullTestSuite(repoRoot || cwd);
  if (!resultado.ok) {
    return {
      decision: 'deny',
      reason:
        'main no puede publicarse con la suite de tests fallando.\n' +
        'Resultado de la suite:\n' + resultado.resumen,
    };
  }
  return { decision: 'ask', reason: 'Suite completa PASS. Confirmar push a main.' };
}

function main() {
  const input = parseHookInput();
  if (input.tool_name !== 'Bash') return allow();

  const command = (input.tool_input && input.tool_input.command) || '';
  if (!command) return allow();
  const cwd = input.cwd || process.cwd();
  const repoRoot = findRepoRoot(cwd);

  // HOOK 1 — base64 inline bloqueado (prioridad máxima, crítico).
  if (containsInlineBase64(command)) {
    return deny(BLOCK_MESSAGE);
  }

  const subcomandos = splitSubcommands(command);

  // HOOK 6 — comandos destructivos claros (antes que push/clone: es lo más grave).
  for (const sub of subcomandos) {
    if (isDestructiveSubcommand(sub, repoRoot || cwd)) {
      return deny(
        'Comando destructivo bloqueado por guardarraíl del proyecto ' +
        '(evita borrado/reseteo masivo accidental del repositorio).'
      );
    }
  }

  // HOOK 5 — protección de main / push.
  for (const sub of subcomandos) {
    const resultado = checkGitPush(sub, repoRoot, cwd);
    if (resultado) {
      if (resultado.decision === 'deny') return deny(resultado.reason);
      return ask(resultado.reason);
    }
  }

  // HOOK 4 — git clone innecesario dentro de un repo ya existente.
  if (repoRoot) {
    for (const sub of subcomandos) {
      if (startsWith(sub, /^git\s+clone\b/i)) {
        return ask(
          'Ya existe un checkout del repositorio.\n' +
          'Evita clonar nuevamente salvo que sea realmente necesario.'
        );
      }
    }
  }

  return allow();
}

main();

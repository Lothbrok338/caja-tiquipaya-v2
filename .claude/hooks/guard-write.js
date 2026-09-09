#!/usr/bin/env node
'use strict';

/**
 * PreToolUse — matcher "Write|Edit".
 *
 * HOOK 1 (parcial): bloquea payload base64 inline en el contenido nuevo.
 * HOOK 2: archivos productivos críticos — DENY en main, ASK en feature branch.
 * HOOK 3: nuevo .py ad hoc en la raíz del repo — ASK.
 *
 * Camino feliz (nada de esto aplica): sale en silencio y rápido.
 */

const fs = require('fs');
const path = require('path');
const { findRepoRoot, getCurrentBranch } = require('./lib/git-utils');
const { containsInlineBase64, BLOCK_MESSAGE } = require('./lib/base64-guard');
const { allow, deny, ask, parseHookInput } = require('./lib/respond');

const ARCHIVOS_CRITICOS = new Set([
  'motor_tiquipaya.py',
  'pipeline_tiquipaya.py',
  'run_batch.py',
  'sap_writer.py',
  'excel_io.py',
  'consolidador_mensual.py',
  'control_asignaciones.py',
]);

function main() {
  const input = parseHookInput();
  const toolName = input.tool_name;
  if (toolName !== 'Write' && toolName !== 'Edit') return allow();

  const toolInput = input.tool_input || {};
  const cwd = input.cwd || process.cwd();

  // HOOK 1 — base64 inline bloqueado (prioridad máxima, crítico).
  // Write: el contenido completo nuevo. Edit: el texto que se inserta
  // (new_string) — nunca old_string, porque QUITAR un blob existente no
  // es "reconstrucción" de un binario.
  const textoNuevo = toolName === 'Write' ? toolInput.content : toolInput.new_string;
  if (containsInlineBase64(textoNuevo)) {
    return deny(BLOCK_MESSAGE);
  }

  const filePath = toolInput.file_path;
  if (!filePath) return allow();

  const repoRoot = findRepoRoot(cwd) || cwd;
  const resolved = path.resolve(cwd, filePath);
  const baseName = path.basename(resolved);

  // HOOK 2 — archivos productivos críticos.
  if (ARCHIVOS_CRITICOS.has(baseName)) {
    const branch = getCurrentBranch(repoRoot);
    if (branch === 'main') {
      return deny(
        'No se modifica código productivo directamente en main.\n' +
        'Crea una rama de trabajo.'
      );
    }
    return ask('Archivo productivo crítico. Confirmar que el usuario autorizó este cambio.');
  }

  // HOOK 3 — nuevo .py ad hoc en la raíz del repo (solo Write; Edit exige
  // que el archivo ya exista, así que nunca crea uno nuevo).
  if (toolName === 'Write' && path.extname(resolved) === '.py') {
    const parentDir = path.dirname(resolved);
    const yaExiste = fs.existsSync(resolved);
    if (parentDir === repoRoot && !yaExiste) {
      return ask(
        'Se está creando un nuevo script Python en la raíz.\n' +
        'Confirma que es un módulo oficial autorizado y no un helper/ad hoc.'
      );
    }
  }

  return allow();
}

main();

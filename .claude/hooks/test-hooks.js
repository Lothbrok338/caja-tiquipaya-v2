#!/usr/bin/env node
'use strict';

/**
 * Prueba específica de los guardarraíles (.claude/hooks/*.js) con
 * entradas JSON sintéticas por stdin, tal como los invoca Claude Code.
 * No depende de ningún framework de test: es un script Node autónomo.
 *
 * Uso: node .claude/hooks/test-hooks.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

const HOOKS_DIR = __dirname;
const GUARD_WRITE = path.join(HOOKS_DIR, 'guard-write.js');
const GUARD_BASH = path.join(HOOKS_DIR, 'guard-bash.js');

let pass = 0;
let fail = 0;
const failures = [];

function runHook(scriptPath, input) {
  const res = spawnSync(process.execPath, [scriptPath], {
    input: JSON.stringify(input),
    encoding: 'utf8',
    timeout: 180000,
  });
  let decision = 'allow'; // silencio = permitido
  let reason = null;
  const out = (res.stdout || '').trim();
  if (out) {
    try {
      const parsed = JSON.parse(out);
      decision = parsed.hookSpecificOutput.permissionDecision;
      reason = parsed.hookSpecificOutput.permissionDecisionReason;
    } catch (e) {
      decision = 'PARSE_ERROR:' + out;
    }
  }
  return { decision, reason, stderr: res.stderr, status: res.status };
}

function check(name, actual, expected) {
  if (actual === expected) {
    pass++;
    console.log(`  ok  - ${name}`);
  } else {
    fail++;
    failures.push(name);
    console.log(`FAIL  - ${name} (esperado=${expected}, obtenido=${actual})`);
  }
}

// ---------------------------------------------------------------------
// Fixtures: dos repos git aislados (tmp), independientes del repo real.
// ---------------------------------------------------------------------

function sh(cmd, cwd) {
  execFileSync('sh', ['-c', cmd], { cwd, stdio: 'pipe' });
}

function crearRepoAislado({ branch, passingTests }) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hooks-test-'));
  sh('git init -q -b ' + branch, dir);
  sh('git config user.email t@example.com && git config user.name Test', dir);
  fs.mkdirSync(path.join(dir, 'tests'));
  fs.writeFileSync(
    path.join(dir, 'tests', 'test_dummy.py'),
    passingTests
      ? 'import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(1, 1)\n'
      : 'import unittest\nclass T(unittest.TestCase):\n    def test_fail(self):\n        self.assertEqual(1, 2)\n'
  );
  fs.writeFileSync(path.join(dir, 'README.md'), '# repo de prueba\n');
  sh('git add -A && git commit -q -m init', dir);
  return dir;
}

const repoMainVerde = crearRepoAislado({ branch: 'main', passingTests: true });
const repoMainRojo = crearRepoAislado({ branch: 'main', passingTests: false });
const repoFeature = crearRepoAislado({ branch: 'main', passingTests: true });
sh('git checkout -q -b feature/x', repoFeature);
const fueraDeRepo = fs.mkdtempSync(path.join(os.tmpdir(), 'hooks-test-norepo-'));

function limpiar() {
  for (const d of [repoMainVerde, repoMainRojo, repoFeature, fueraDeRepo]) {
    fs.rmSync(d, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------
// BASE64
// ---------------------------------------------------------------------
console.log('BASE64');
const blobLargo = 'A'.repeat(600);
const shaCorto = '3f786850e387550fdab836ed7e6dc881de23001b0f95e5f2c9f14f8f89e4f8f'; // 64 chars

check('1. blob inline largo en Write -> DENY',
  runHook(GUARD_WRITE, { tool_name: 'Write', cwd: repoFeature, tool_input: { file_path: 'x.txt', content: blobLargo } }).decision,
  'deny');

check('2. blob inline largo en Edit -> DENY',
  runHook(GUARD_WRITE, { tool_name: 'Edit', cwd: repoFeature, tool_input: { file_path: 'README.md', old_string: 'a', new_string: blobLargo } }).decision,
  'deny');

check('3. echo blob | base64 -d -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: `echo "${blobLargo}" | base64 -d` } }).decision,
  'deny');

check('4. base64 -d archivo.b64 -> permitido',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'base64 -d archivo.b64 > salida.bin' } }).decision,
  'allow');

check('5. SHA256 de 64 caracteres -> permitido',
  runHook(GUARD_WRITE, { tool_name: 'Write', cwd: repoFeature, tool_input: { file_path: 'x.txt', content: 'sha256=' + shaCorto } }).decision,
  'allow');

// ---------------------------------------------------------------------
// ARCHIVOS CRÍTICOS
// ---------------------------------------------------------------------
console.log('ARCHIVOS');

check('6. editar motor_tiquipaya.py en main -> DENY',
  runHook(GUARD_WRITE, { tool_name: 'Edit', cwd: repoMainVerde, tool_input: { file_path: 'motor_tiquipaya.py', old_string: 'a', new_string: 'b' } }).decision,
  'deny');

check('7. editarlo en feature branch -> ASK',
  runHook(GUARD_WRITE, { tool_name: 'Edit', cwd: repoFeature, tool_input: { file_path: 'motor_tiquipaya.py', old_string: 'a', new_string: 'b' } }).decision,
  'ask');

check('8. editar README/HANDOFF normal -> permitido',
  runHook(GUARD_WRITE, { tool_name: 'Edit', cwd: repoMainVerde, tool_input: { file_path: 'README.md', old_string: 'a', new_string: 'b' } }).decision,
  'allow');

// ---------------------------------------------------------------------
// NUEVO .py
// ---------------------------------------------------------------------
console.log('NUEVO PY');

check('9. crear helper_nuevo.py en raíz -> ASK',
  runHook(GUARD_WRITE, { tool_name: 'Write', cwd: repoFeature, tool_input: { file_path: 'helper_nuevo.py', content: 'x = 1\n' } }).decision,
  'ask');

fs.writeFileSync(path.join(repoFeature, 'ya_existe.py'), 'x = 1\n');
check('10. modificar .py ya existente -> no aplica regla de nuevo archivo (permitido)',
  runHook(GUARD_WRITE, { tool_name: 'Write', cwd: repoFeature, tool_input: { file_path: 'ya_existe.py', content: 'x = 2\n' } }).decision,
  'allow');

check('11. crear tests/test_x.py -> permitido',
  runHook(GUARD_WRITE, { tool_name: 'Write', cwd: repoFeature, tool_input: { file_path: 'tests/test_x.py', content: 'x = 1\n' } }).decision,
  'allow');

// ---------------------------------------------------------------------
// GIT
// ---------------------------------------------------------------------
console.log('GIT');

check('12. git clone dentro del repo -> ASK',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'git clone https://example.com/algo.git' } }).decision,
  'ask');

check('13. git clone fuera -> permitido',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: fueraDeRepo, tool_input: { command: 'git clone https://example.com/algo.git' } }).decision,
  'allow');

check('14. force push main -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoMainVerde, tool_input: { command: 'git push --force origin main' } }).decision,
  'deny');

check('14b. force push main (-f) -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoMainVerde, tool_input: { command: 'git push -f origin main' } }).decision,
  'deny');

console.log('  (15/16 ejecutan la suite real del repo aislado: puede tardar unos segundos)');
check('15. push normal a main con tests fallidos -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoMainRojo, tool_input: { command: 'git push origin main' } }).decision,
  'deny');

check('16. push normal a main con tests PASS -> ASK',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoMainVerde, tool_input: { command: 'git push origin main' } }).decision,
  'ask');

check('16b. push normal a una rama que no es main -> permitido (no corre tests)',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'git push origin feature/x' } }).decision,
  'allow');

// ---------------------------------------------------------------------
// DESTRUCTIVOS
// ---------------------------------------------------------------------
console.log('DESTRUCTIVOS');

check('17. git reset --hard -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'git reset --hard origin/main' } }).decision,
  'deny');

check('18. git clean -fd -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'git clean -fd' } }).decision,
  'deny');

check('18b. git clean -n (dry-run) -> permitido',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'git clean -n' } }).decision,
  'allow');

check('18c. rm -rf <raíz del proyecto> -> DENY',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: `rm -rf ${repoFeature}` } }).decision,
  'deny');

check('18d. rm -rf de un archivo temporal individual -> permitido',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: 'rm -rf /tmp/algo-temporal-xyz' } }).decision,
  'allow');

// Regresión: un comando real (p. ej. `git commit`) cuyo ARGUMENTO de
// texto (mensaje de commit) simplemente MENCIONA "git reset --hard" o
// "rm -rf" como documentación no debe bloquearse — solo el comando que
// realmente se ejecuta importa (ver startsWith() en guard-bash.js).
const mensajeConPalabrasPeligrosas =
  'git commit -m "$(cat <<\'EOF\'\n' +
  'Documenta que el hook bloquea git reset --hard, rm -rf y git clean -fd.\n' +
  'EOF\n' +
  ')"';
check('18e. commit cuyo mensaje MENCIONA comandos peligrosos -> permitido (no falso positivo)',
  runHook(GUARD_BASH, { tool_name: 'Bash', cwd: repoFeature, tool_input: { command: mensajeConPalabrasPeligrosas } }).decision,
  'allow');

// ---------------------------------------------------------------------

limpiar();

console.log(`\n${pass} ok, ${fail} fallidas`);
if (fail > 0) {
  console.log('Fallidas: ' + failures.join(', '));
  process.exit(1);
}
process.exit(0);

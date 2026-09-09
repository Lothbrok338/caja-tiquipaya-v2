'use strict';

/**
 * Utilidades Git mínimas, sin dependencias externas y sin invocar el
 * binario `git` (lectura directa de .git/HEAD): rápido y portable entre
 * Windows/Linux/CI. Suficiente para lo que los guardarraíles necesitan
 * (rama actual, "¿estoy dentro de un repo?") — no reemplaza a git.
 */

const fs = require('fs');
const path = require('path');

/** Busca hacia arriba desde startDir hasta encontrar un `.git`. */
function findRepoRoot(startDir) {
  let dir = path.resolve(startDir);
  while (true) {
    if (fs.existsSync(path.join(dir, '.git'))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/** Devuelve el nombre de la rama actual, o null si no puede determinarse. */
function getCurrentBranch(repoRoot) {
  try {
    const dotGit = path.join(repoRoot, '.git');
    let gitDir = dotGit;
    if (fs.statSync(dotGit).isFile()) {
      // Worktree: .git es un archivo "gitdir: <ruta>".
      const contents = fs.readFileSync(dotGit, 'utf8').trim();
      const m = contents.match(/^gitdir:\s*(.+)$/);
      if (m) gitDir = path.resolve(repoRoot, m[1]);
    }
    const head = fs.readFileSync(path.join(gitDir, 'HEAD'), 'utf8').trim();
    const m = head.match(/^ref:\s*refs\/heads\/(.+)$/);
    if (m) return m[1];
    return null; // HEAD desprendido: no hay "rama actual".
  } catch (e) {
    return null;
  }
}

module.exports = { findRepoRoot, getCurrentBranch };

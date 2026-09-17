/**
 * tests_v3/n8n_publicacion_mensual/logic_reference.js — FASE 12D.
 *
 * Copia de referencia EXACTA (equivalente logico, ver nota en
 * tests_v3/n8n_publicacion_oficial/logic_reference.js) de la logica de
 * idempotencia de los 3 subworkflows n8n reutilizables creados en FASE 12D:
 *
 *   - TIQ V3 · 07C DESCARGAR ARCHIVO OFICIAL SI EXISTE · DRIVE (fn7lLjHsiMd48DGK)
 *   - TIQ V3 · 07D PUBLICAR ARCHIVO OFICIAL (crear o actualizar) · DRIVE (HhuQCVP2oCubavzY)
 *   - TIQ V3 · 07E BUSCAR O CREAR CARPETA OFICIAL · DRIVE (Lht5xRinJ9nJpHCW)
 *
 * Los tres comparten el mismo patron "buscar por nombre exacto -> 0/1/>1"
 * ya usado en 06B (FASE 11A.1): 0 coincidencias -> crear/descargar-nada,
 * 1 coincidencia -> reutilizar/actualizar, >1 -> ERROR_AMBIGUO_* y detener
 * sin tocar nada mas.
 *
 * Mantener sincronizado con los nodos "VERIFICAR - Coincidencia exacta" de
 * cada uno de los 3 subworkflows.
 */
'use strict';

function verificarCoincidenciaExacta(items, nombreEsperado, codigoErrorAmbiguo) {
  const exactos = items.filter(function (it) { return it && it.name === nombreEsperado && it.id; });
  if (exactos.length > 1) {
    throw new Error(
      codigoErrorAmbiguo + ': se encontraron ' + exactos.length + ' coincidencias para "' +
      nombreEsperado + '". No se continua hasta resolver el duplicado manualmente.'
    );
  }
  return { existe: exactos.length === 1, id: exactos.length === 1 ? exactos[0].id : null };
}

// 07C: 0 -> nada que descargar; 1 -> descargar; >1 -> ERROR_AMBIGUO_DESCARGA.
function decidirDescarga(items, nombreEsperado) {
  const r = verificarCoincidenciaExacta(items, nombreEsperado, 'ERROR_AMBIGUO_DESCARGA');
  return { encontrado: r.existe, fileId: r.id };
}

// 07E: 0 -> crear carpeta; 1 -> reutilizar; >1 -> ERROR_AMBIGUO_CARPETA.
function decidirCarpeta(items, nombreEsperado) {
  const r = verificarCoincidenciaExacta(items, nombreEsperado, 'ERROR_AMBIGUO_CARPETA');
  return { existe: r.existe, carpetaId: r.id };
}

// 07D: 0 -> crear; 1 + modo_si_existe='actualizar' -> actualizar contenido;
// 1 + modo_si_existe='mantener' -> reutilizar SIN tocar (artefactos
// inmutables como el GLOBAL, mismo criterio que SAP/RESULTADO diarios en
// 06B); >1 -> ERROR_AMBIGUO_PUBLICACION.
function decidirPublicacion(items, nombreEsperado, modoSiExiste) {
  const r = verificarCoincidenciaExacta(items, nombreEsperado, 'ERROR_AMBIGUO_PUBLICACION');
  if (!r.existe) {
    return { accion: 'crear', fileId: null };
  }
  if (modoSiExiste === 'actualizar') {
    return { accion: 'actualizar', fileId: r.id };
  }
  return { accion: 'reutilizar', fileId: r.id };
}

module.exports = {
  verificarCoincidenciaExacta,
  decidirDescarga,
  decidirCarpeta,
  decidirPublicacion,
};

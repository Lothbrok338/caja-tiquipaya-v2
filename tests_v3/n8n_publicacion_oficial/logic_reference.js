/**
 * tests_v3/n8n_publicacion_oficial/logic_reference.js — FASE 11A.1.
 *
 * Copia de referencia EXACTA de la logica de idempotencia que vive dentro
 * de los nodos Code del workflow n8n "TIQ V3 · 06B PUBLICACION OFICIAL ·
 * DRIVE" (creado via create_workflow_from_code). Los nodos Code de n8n
 * corren en un sandbox sin acceso a filesystem/require de archivos del
 * proyecto (misma limitacion ya documentada en v3/TECHNICAL_DEBT.md
 * DEBT-001 para el subworkflow 01 INGESTA): el jsCode embebido en cada
 * nodo es, por fuerza, la UNICA copia que realmente se ejecuta contra
 * Drive. Este archivo es una copia deliberada y explicita para poder
 * probar esa misma logica con Node "plano" (sin n8n, sin Drive), tal como
 * test_frontend.js ya hace para el HTML del frontend.
 *
 * NOTA: equivalente logico, no copia textual -- opera sobre objetos planos
 * ({name, id}) en vez de los items {json:{name,id}} que envuelve n8n, para
 * poder probarse con Node puro. El ALGORITMO (que se busca, cuando se
 * lanza ERROR_AMBIGUO_*, cuando se confia en el fileId de ingesta vs
 * cuando se reconcilia por nombre) es identico linea a linea al jsCode de
 * cada nodo.
 *
 * Mantener sincronizado con los nodos:
 *   - VERIFICAR - SAP existente (idempotencia)
 *   - VERIFICAR - Resultado existente (idempotencia)
 *   - VERIFICAR - Cierre en ENTRADA (fileId primario + reconciliacion)
 *   - VERIFICAR - Cierre en PROCESADOS (retry)
 * del workflow n8n wcgxNei3duWfMDp1 (reemplaza a PQocEfOB00Bxvy0p, FASE 11A).
 */
'use strict';

// ---------------------------------------------------------------------
// SAP / RESULTADO: mismo patron reentrante para ambos -- busca por nombre
// oficial exacto en la carpeta destino antes de crear nada.
// ---------------------------------------------------------------------
function verificarArtefactoExistente(items, nombreEsperado, codigoErrorAmbiguo) {
  const exactos = items.filter(function (it) { return it && it.name === nombreEsperado && it.id; });
  if (exactos.length > 1) {
    throw new Error(
      codigoErrorAmbiguo + ': se encontraron ' + exactos.length + ' archivos llamados "' +
      nombreEsperado + '" en la carpeta oficial. No se sube ni se continua hasta resolver el duplicado manualmente.'
    );
  }
  return { yaExiste: exactos.length === 1, fileId: exactos.length === 1 ? exactos[0].id : null };
}

// ---------------------------------------------------------------------
// CIERRE ORIGINAL -- el drive_file_id de INGESTA es el identificador
// PRIMARIO; la busqueda por nombre exacto en 00_ENTRADA_CIERRES es
// VERIFICACION/reconciliacion (nunca el mecanismo principal).
// ---------------------------------------------------------------------
function verificarCierreEnEntrada(items, archivoEsperado, driveFileIdIngesta) {
  const exactos = items.filter(function (it) { return it && it.name === archivoEsperado && it.id; });
  if (exactos.length > 1) {
    throw new Error(
      'ERROR_AMBIGUO_CIERRE_ENTRADA: se encontraron ' + exactos.length + ' archivos llamados "' +
      archivoEsperado + '" en 00_ENTRADA_CIERRES. No se mueve nada hasta resolver el duplicado manualmente.'
    );
  }
  if (exactos.length === 1) {
    const encontrado = exactos[0];
    if (driveFileIdIngesta && encontrado.id !== driveFileIdIngesta) {
      throw new Error(
        'ERROR_FILEID_INGESTA_NO_COINCIDE: el fileId detectado en INGESTA (' + driveFileIdIngesta +
        ') no coincide con el fileId actual de "' + archivoEsperado + '" en 00_ENTRADA_CIERRES (' +
        encontrado.id + '). No se mueve nada.'
      );
    }
    return { encontradoEnEntrada: true, cierreFileId: encontrado.id };
  }
  // 0 coincidencias en ENTRADA: puede ser un retry sobre un cierre YA movido.
  return { encontradoEnEntrada: false, cierreFileId: driveFileIdIngesta || null };
}

function verificarCierreEnProcesados(items, archivoEsperado) {
  const exactos = items.filter(function (it) { return it && it.name === archivoEsperado && it.id; });
  if (exactos.length > 1) {
    throw new Error(
      'ERROR_AMBIGUO_CIERRE_PROCESADOS: se encontraron ' + exactos.length + ' archivos llamados "' +
      archivoEsperado + '" en 03_PROCESADOS. Revisar manualmente.'
    );
  }
  if (exactos.length === 1) {
    return { id: exactos[0].id, yaEnProcesados: true };
  }
  throw new Error(
    'ERROR_CIERRE_NO_LOCALIZADO: "' + archivoEsperado +
    '" no esta ni en 00_ENTRADA_CIERRES ni en 03_PROCESADOS. No se puede publicar oficialmente sin localizar el cierre original.'
  );
}

// ---------------------------------------------------------------------
// MARKER: idempotencia global -- si ya existe, YA_PUBLICADO sin tocar nada.
// ---------------------------------------------------------------------
function markerYaExiste(items) {
  return items.length > 0 && !!items[0].id;
}

module.exports = {
  verificarArtefactoExistente,
  verificarCierreEnEntrada,
  verificarCierreEnProcesados,
  markerYaExiste,
};

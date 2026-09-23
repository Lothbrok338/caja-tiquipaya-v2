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
 *
 * BLOQUE 2 (RECTIFICAR CIERRE PUBLICADO) agrega, mantenidos sincronizados con:
 *   - VALIDAR - Identidades previas unicas (rectificacion)
 *   - RESOLVER - Marker anterior unico (rectificacion)
 *   - CONSTRUIR - Salida RECTIFICADO_OFICIAL
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

// ---------------------------------------------------------------------
// AISLAMIENTO DRIVE POR CAJA -- copia de referencia EXACTA del nodo Code
// "RESOLVER - Destinos Drive por caja" (presente, con el mismo jsCode, en
// AMBOS workflows: 06B PUBLICACION OFICIAL wcgxNei3duWfMDp1 y PREFLIGHT
// OFICIAL sJVgoBRpBntc96vf). Espejo de config_drive_oficial.py en el
// backend Python; mantener ambas copias sincronizadas.
// ---------------------------------------------------------------------
const DEFAULTS_TIQ = {
  entrada: '1ntneoE3MI-25FyPXUymXEvIJmnaZWyJ1',
  sap: '1mid4gUHnCmZbISlsAYMwWta3RudTSE13',
  resultado: '16Z7Uhf-NgiZ6YuqWLnReaIozRIiOg5HO',
  procesados: '1BkNC6lnonMM7YeWDKck-TM8WTyY2BJJP',
  marker: '1i8wXRM-2yiH5N3SPOEd4eEqZnizCeCGu',
};

const PREFIJOS_CAJA = {
  tiquipaya: ['SAP_TIQ_', 'SAP_GLOBAL_TIQ_', 'RESULTADO_TIQ_'],
  america: ['SAP_AME_', 'SAP_GLOBAL_AME_', 'RESULTADO_AME_'],
};

function validarPrefijoArchivo(caja, nombreArchivo) {
  if (!nombreArchivo) return;
  const propios = PREFIJOS_CAJA[caja];
  if (propios.some(function (p) { return nombreArchivo.startsWith(p); })) return;
  const otras = Object.keys(PREFIJOS_CAJA).filter(function (c) { return c !== caja; });
  for (const otra of otras) {
    if (PREFIJOS_CAJA[otra].some(function (p) { return nombreArchivo.startsWith(p); })) {
      throw new Error(
        'PREFIJO_CAJA_NO_COINCIDE: "' + nombreArchivo + '" tiene prefijo de ' +
        otra.toUpperCase() + ' pero se esta publicando como ' + caja.toUpperCase() + '.'
      );
    }
  }
}

function resolverDestinosDrive(cajaCruda, env) {
  env = env || {};
  const caja = (cajaCruda || 'tiquipaya').toString().trim().toLowerCase();
  if (caja !== 'tiquipaya' && caja !== 'america') {
    throw new Error('CAJA_DESCONOCIDA: "' + caja + '". Cajas validas: america, tiquipaya.');
  }

  function resolverDestino(clave) {
    const envVar = 'DRIVE_' + clave.toUpperCase() + '_' + (caja === 'america' ? 'AME' : 'TIQ');
    const valor = env[envVar];
    if (valor) return valor;
    if (caja === 'tiquipaya') return DEFAULTS_TIQ[clave];
    throw new Error(
      'DRIVE_AME_PENDIENTE: falta configurar ' + envVar +
      ' (carpeta "' + clave + '" de CAJA AMERICA todavia no existe en Drive).'
    );
  }

  return {
    caja: caja,
    folder_entrada: resolverDestino('entrada'),
    folder_sap: resolverDestino('sap'),
    folder_resultado: resolverDestino('resultado'),
    folder_procesados: resolverDestino('procesados'),
    folder_marker: resolverDestino('marker'),
  };
}

// ---------------------------------------------------------------------
// BLOQUE 2 -- RECTIFICAR CIERRE PUBLICADO (sustitucion oficial de una
// publicacion previa). Copia de referencia EXACTA de la logica de los
// nodos Code nuevos del workflow n8n 06B PUBLICACION OFICIAL (rama
// SAP existe + rectificacion=true):
//   - VALIDAR - Identidades previas unicas (rectificacion)
//   - RESOLVER - Marker anterior unico (rectificacion)
//   - CONSTRUIR - Salida RECTIFICADO_OFICIAL
// PASO C: exactamente UN SAP, UN RESULTADO, UN cierre en 03_PROCESADOS y
// UN cierre nuevo en 00_ENTRADA_CIERRES (cuyo fileId coincida con
// INGESTA) -- 0 o >1 en cualquiera de los cuatro -> fail closed, nada se
// escribe. PASO B: el marker anterior se resuelve por metadata real
// (ArchivoSAP + ArchivoOrigen + FechaCierre, campos que ya produce
// pipeline_tiquipaya.construir_registro_control()/construir_marcador_procesado()),
// nunca adivinando el SHA en el nombre del archivo.
// ---------------------------------------------------------------------

function validarIdentidadesPreviasRectificacion(sapFileIdAnterior, resultadoItems, nombreResultado,
                                                 procesadosItems, archivoEsperado,
                                                 entradaItems, driveFileIdIngesta) {
  if (!sapFileIdAnterior) {
    throw new Error('ERROR_RECTIFICACION_SAP_NO_ENCONTRADO: no hay un SAP oficial previo; no hay nada que rectificar.');
  }

  function unico(items, nombreBuscado, etiqueta) {
    const exactos = items.filter(function (it) { return it && it.name === nombreBuscado && it.id; });
    if (exactos.length === 0) {
      throw new Error('ERROR_RECTIFICACION_' + etiqueta + '_NO_ENCONTRADO: no se encontro exactamente un "' + nombreBuscado + '" oficial previo. No se modifica nada.');
    }
    if (exactos.length > 1) {
      throw new Error('ERROR_RECTIFICACION_' + etiqueta + '_AMBIGUO: se encontraron ' + exactos.length + ' archivos llamados "' + nombreBuscado + '". No se modifica nada hasta resolver el duplicado manualmente.');
    }
    return exactos[0].id;
  }

  const resultadoFileIdAnterior = unico(resultadoItems, nombreResultado, 'RESULTADO');
  const cierreProcesadoFileIdAnterior = unico(procesadosItems, archivoEsperado, 'CIERRE_PROCESADOS');

  const candidatosEntrada = entradaItems.filter(function (it) { return it && it.name === archivoEsperado && it.id; });
  if (candidatosEntrada.length === 0) {
    throw new Error('ERROR_RECTIFICACION_CIERRE_NUEVO_NO_ENCONTRADO: no se encontro el cierre corregido "' + archivoEsperado + '" en 00_ENTRADA_CIERRES. No hay nada que rectificar sin el cierre nuevo.');
  }
  if (candidatosEntrada.length > 1) {
    throw new Error('ERROR_RECTIFICACION_CIERRE_NUEVO_AMBIGUO: se encontraron ' + candidatosEntrada.length + ' archivos llamados "' + archivoEsperado + '" en 00_ENTRADA_CIERRES.');
  }
  const cierreNuevoEncontrado = candidatosEntrada[0];
  if (driveFileIdIngesta && cierreNuevoEncontrado.id !== driveFileIdIngesta) {
    throw new Error('ERROR_RECTIFICACION_FILEID_INGESTA_NO_COINCIDE: el fileId detectado en INGESTA (' + driveFileIdIngesta + ') no coincide con el fileId actual de "' + archivoEsperado + '" en 00_ENTRADA_CIERRES (' + cierreNuevoEncontrado.id + '). No se modifica nada.');
  }

  return {
    sap_file_id_anterior: sapFileIdAnterior,
    resultado_file_id_anterior: resultadoFileIdAnterior,
    cierre_procesado_file_id_anterior: cierreProcesadoFileIdAnterior,
    cierre_nuevo_file_id_entrada: cierreNuevoEncontrado.id,
  };
}

function resolverMarkerAnteriorRectificacion(markersConContenido, nombreSapOficial, archivoEsperado, fecha, shaNuevo) {
  const candidatos = markersConContenido.filter(function (m) {
    if (!m || !m.contenido) return false;
    const c = m.contenido;
    return c.ArchivoSAP === nombreSapOficial && c.ArchivoOrigen === archivoEsperado && c.FechaCierre === fecha;
  });

  if (candidatos.length === 0) {
    throw new Error('ERROR_MARKER_ANTERIOR_NO_ENCONTRADO: no se pudo identificar de forma determinista el marcador de la publicacion oficial anterior. FAIL CLOSED: no se modifica nada.');
  }
  if (candidatos.length > 1) {
    throw new Error('ERROR_AMBIGUO_MARKER_ANTERIOR: se encontraron ' + candidatos.length + ' marcadores cuya metadata coincide con esta publicacion anterior. FAIL CLOSED: no se modifica nada hasta resolver manualmente.');
  }

  const markerAnterior = candidatos[0];
  const shaAnterior = markerAnterior.contenido.HashOrigen || null;
  if (!shaAnterior) {
    throw new Error('ERROR_MARKER_ANTERIOR_SIN_HASH: el marcador anterior identificado no trae HashOrigen. FAIL CLOSED.');
  }
  if (shaAnterior === shaNuevo) {
    throw new Error('ERROR_RECTIFICACION_SHA_IGUAL: el SHA256 nuevo coincide con el anterior; esto es idempotencia (mismo cierre), no una rectificacion. Use PUBLICAR normal.');
  }

  return { marker_file_id_anterior: markerAnterior.id, sha_anterior: shaAnterior, sha_nuevo: shaNuevo };
}

module.exports = {
  verificarArtefactoExistente,
  verificarCierreEnEntrada,
  verificarCierreEnProcesados,
  markerYaExiste,
  validarPrefijoArchivo,
  resolverDestinosDrive,
  validarIdentidadesPreviasRectificacion,
  resolverMarkerAnteriorRectificacion,
};

/**
 * tests_v3/n8n_control1_institucional_drive/logic_reference.js
 *
 * Copia de referencia EXACTA de la logica del nodo Code "DECIDIR - Publicar
 * CONTROL1 oficial" del workflow n8n BACKEND DEV (aLs1f3GMqswbaENA), tal
 * como logic_reference.js ya hace para 06B PUBLICACION OFICIAL (ver
 * tests_v3/n8n_publicacion_oficial/logic_reference.js). Los nodos Code de
 * n8n no pueden importar archivos del proyecto, asi que el jsCode embebido
 * en el nodo es la UNICA copia que realmente corre contra Drive; este
 * archivo permite probar ese mismo algoritmo con Node puro (sin n8n, sin
 * Drive real).
 *
 * POR QUE EXISTE (recuperacion de una publicacion oficial de CONTROL 1
 * interrumpida a mitad de camino, ver V3_OPEN_MONTH_STATE.md): la
 * publicacion a Drive de GLOBAL TIQ y GLOBAL AME es SECUENCIAL (dos items,
 * "EJECUTAR 07D publicar CONTROL1" en modo "each"). Si TIQ se sube pero AME
 * falla, un reintento vuelve a llamar al webhook `control1` con el MISMO
 * body (mismas correcciones_tiq/ame). La correccion LOCAL ya es
 * recuperable (ver v3/control1_institucional.
 * aplicar_correcciones_institucional_recuperable): en el reintento, un
 * GLOBAL que ya quedo en su estado FINAL localmente no vuelve a corregirse
 * ni falla, asi que `ejecutar_control1_institucional` puede terminar en
 * YA_PROCESADO_SIN_CAMBIOS (el par TIQ/AME local ya esta cerrado desde el
 * intento anterior) en vez de volver a marcar `historico_actualizado`.
 *
 * Version anterior (bug): `esCierre` exigia `historico_actualizado === true`
 * EN ESA MISMA corrida, asi que en el reintento `esCierre` daba false y
 * NINGUN GLOBAL se volvia a intentar publicar -- AME se quedaba
 * indefinidamente desactualizado en Drive con el par ya cerrado localmente.
 *
 * Version corregida (aqui): `cierreCompletado` es true tanto si el
 * historico institucional se acaba de actualizar EN ESTA corrida (cierre
 * fresco) como si el par TIQ/AME ya estaba cerrado de una corrida anterior
 * (`estado === 'YA_PROCESADO_SIN_CAMBIOS'`, reintento). 07D sube cada
 * archivo en modo "actualizar" (sobrescritura), asi que reintentar la
 * subida de un archivo que YA quedo correcto en Drive es un no-op
 * inofensivo -- nunca hace falta comparar contenido para decidir republicar.
 * Cualquier otro estado (p.ej. GLOBAL_MODIFICADO_REQUIERE_REVISION: el par
 * actual difiere del que ya quedo cerrado en el historico) NUNCA cuenta
 * como cierre completado: no se publica nada y se exige revision humana --
 * fail closed, igual criterio que la capa local.
 */
'use strict';

function vacio() {
  return { debe_publicar: false, hay_detalle: false, hay_historico: false, publicar_global_tiq: false, publicar_global_ame: false };
}

/**
 * decidirPublicacionControl1(r, body, nombreDetalleEsperado)
 *   r: resultado de v3.control1_institucional.ejecutar_control1_institucional
 *      (mezclado con {resultado, dir_entrada, modo} por v3/dev_api.py).
 *   body: body del webhook `control1` (modo, correcciones_tiq, correcciones_ame).
 *   nombreDetalleEsperado: nombre canonico del detalle del periodo pedido
 *      (equivalente a `rc.nombre_detalle` en el nodo real).
 */
function decidirPublicacionControl1(r, body, nombreDetalleEsperado) {
  const modo = (body || {}).modo || 'dev';
  if (modo !== 'official') {
    return vacio();
  }
  r = r || {};
  if (r.resultado === 'ERROR' || r.estado === 'ERROR_TECNICO') {
    return vacio();
  }

  const hayDetalle = typeof r.ruta_detalle_json === 'string' && r.ruta_detalle_json.split('/').pop() === nombreDetalleEsperado;

  // Cierre fresco EN ESTA corrida, o par TIQ/AME ya cerrado de una corrida
  // anterior (reintento tras publicacion parcial a Drive): en ambos casos
  // el par local esta en su estado FINAL y es seguro (re)publicar. Cualquier
  // otro estado (GLOBAL_MODIFICADO_REQUIERE_REVISION, REVISAR_DUPLICADOS_
  // ENCONTRADOS, etc.) NUNCA se trata como cierre completado.
  const cierreCompletado = r.modo === 'cierre' && (r.historico_actualizado === true || r.estado === 'YA_PROCESADO_SIN_CAMBIOS');
  const hayHistorico = cierreCompletado;

  const correccionesTiq = Array.isArray(body.correcciones_tiq) ? body.correcciones_tiq : [];
  const correccionesAme = Array.isArray(body.correcciones_ame) ? body.correcciones_ame : [];
  const publicarGlobalTiq = cierreCompletado && correccionesTiq.length > 0;
  const publicarGlobalAme = cierreCompletado && correccionesAme.length > 0;

  return {
    debe_publicar: hayDetalle || hayHistorico || publicarGlobalTiq || publicarGlobalAme,
    hay_detalle: hayDetalle,
    hay_historico: hayHistorico,
    publicar_global_tiq: publicarGlobalTiq,
    publicar_global_ame: publicarGlobalAme,
  };
}

module.exports = { decidirPublicacionControl1 };

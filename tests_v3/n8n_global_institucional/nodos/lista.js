const d = $('DECIDIR - Publicar GLOBAL institucional oficial').item.json;
const carpetaId = $json.carpeta_id;
// Los TRES GLOBAL (TIQ, AME, INSTITUCIONAL) + su resultado/mapa de origen,
// todos a la MISMA carpeta institucional GLOBAL. Nunca botones separados:
// esta lista es interna a la orquestacion de un solo click.
const archivos = [
  d.ruta_global_tiq, d.ruta_resultado_tiq,
  d.ruta_global_ame, d.ruta_resultado_ame,
  d.ruta_global_institucional, d.ruta_mapa_origen_institucional,
].filter(Boolean);
return archivos.map(function (ruta) {
  return { json: { carpeta_id: carpetaId, nombre_archivo: ruta.split('/').pop(), ruta_local_origen: ruta, modo_si_existe: 'actualizar' } };
});
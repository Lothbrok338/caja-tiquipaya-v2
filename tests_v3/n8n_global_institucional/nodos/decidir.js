const modo = (($('WEBHOOK global institucional').item.json.body) || {}).modo || 'dev';
const r = $json.data;
const guardActivo = ['true', '1', 'yes'].includes(String($env.TIQ_BLOCK_OFFICIAL_PUBLISH || '').trim().toLowerCase());
// SHADOW: con el guard activo, debe_publicar=false aunque el request diga modo='official'
// (mismo criterio que 'DECIDIR - Publicar GLOBAL oficial').
// Solo se publica si LOS TRES (TIQ, AME e INSTITUCIONAL) llegaron a un GLOBAL
// valido -- nunca institucional parcial: si TIQ o AME hubieran fallado, esta
// rama nunca se ejecuta (dev_api.generar_global_institucional ya propaga la
// excepcion antes de fusionar, ver INTERPRETAR->salida ERROR).
const debePublicar = !guardActivo && modo === 'official'
  && r.resultado_tiq && r.resultado_tiq.estado === 'VALIDADO_PENDIENTE_PUBLICACION'
  && r.resultado_ame && r.resultado_ame.estado === 'VALIDADO_PENDIENTE_PUBLICACION';
return [{ json: {
  debe_publicar: debePublicar,
  ruta_global_tiq: r.ruta_global_tiq,
  ruta_resultado_tiq: r.resultado_tiq && r.resultado_tiq.ruta_resultado_json,
  ruta_global_ame: r.ruta_global_ame,
  ruta_resultado_ame: r.resultado_ame && r.resultado_ame.ruta_resultado_json,
  ruta_global_institucional: r.ruta_global_institucional,
  ruta_mapa_origen_institucional: r.ruta_mapa_origen_institucional,
} }];
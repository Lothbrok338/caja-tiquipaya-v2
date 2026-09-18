// Universo de GLOBAL = SAP diarios validos del periodo en la carpeta SAP oficial de Drive.
// Cada SAP conserva nombre, fileId, fecha inferida e identidad propia (nunca se elige por posicion).
const r = $('RESOLVER carpeta SAP oficial').first().json;
const RE_V3 = /^SAP_TIQ_(\d{2})-(\d{2})-(\d{4})\.xlsx$/i;
const RE_LEGACY = /^SAP_(\d{2})-(\d{2})-(\d{4})\.xlsx$/i;

const validos = [];
const veces = {};
for (const it of $input.all()) {
  const f = it.json || {};
  if (!f.id || !f.name) continue;
  const nombre = String(f.name);
  if (nombre.startsWith('~$') || nombre.startsWith('.') || nombre.toLowerCase().endsWith('.tmp')) continue;
  let m = RE_V3.exec(nombre);
  let origen = 'v3';
  if (!m) { m = RE_LEGACY.exec(nombre); origen = 'legacy'; }
  if (!m) continue;
  const dia = Number(m[1]);
  const mesN = Number(m[2]);
  const anioN = Number(m[3]);
  if (anioN !== r.anio || mesN !== r.mes) continue;
  const d = new Date(Date.UTC(anioN, mesN - 1, dia));
  if (d.getUTCDate() !== dia || d.getUTCMonth() !== mesN - 1) continue;
  veces[nombre] = (veces[nombre] || 0) + 1;
  validos.push({
    id: String(f.id), name: nombre, origen: origen,
    fecha: anioN + '-' + String(mesN).padStart(2, '0') + '-' + String(dia).padStart(2, '0'),
    ruta_destino: r.dir_entrada + '/' + nombre,
  });
}

const repetidos = Object.keys(veces).filter(function (n) { return veces[n] > 1; });
if (repetidos.length) {
  throw new Error('ERROR_AMBIGUO_SAP_DRIVE: hay mas de un archivo con el mismo nombre exacto en la carpeta SAP oficial (' + repetidos.join(', ') + '). No se materializa nada hasta resolver el duplicado manualmente.');
}

validos.sort(function (a, b) { return a.fecha < b.fecha ? -1 : (a.fecha > b.fecha ? 1 : (a.name < b.name ? -1 : 1)); });
if (!validos.length) {
  return [{ json: { hay_sap: false, cantidad: 0 } }];
}
return validos.map(function (v) {
  return { json: Object.assign({ hay_sap: true, cantidad: validos.length }, v) };
});

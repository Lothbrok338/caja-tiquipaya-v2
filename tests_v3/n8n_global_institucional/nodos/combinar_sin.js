const base = $('INTERPRETAR resultado global institucional').item.json.data;
return [{ json: { data: Object.assign({}, base, { publicacion_oficial: { publicado: false } }) } }];
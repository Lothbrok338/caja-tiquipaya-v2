const base = $('INTERPRETAR resultado global institucional').item.json.data;
const subidas = $input.all().map(function(i){ return i.json; }).filter(function(j){ return j && Object.keys(j).length; });
return [{ json: { data: Object.assign({}, base, { publicacion_oficial: { publicado: true, archivos: subidas } }) } }];
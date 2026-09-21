// Frontend/backend integration tests for n8n_frontend/v3_control_cierres.html
// (FASE 9). Uses jsdom to load the REAL page + REAL script, and mocks only
// window.fetch (the network boundary) — nothing about the page's own logic
// is mocked or reimplemented here.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

// Portabilidad (migración Railway 2026-09): antes hardcodeaba
// "/workspaces/caja-tiquipaya-v2" (ruta fija del Codespace). Resuelto
// relativo a este archivo para funcionar en cualquier checkout.
const HTML_PATH = path.join(__dirname, "..", "..", "n8n_frontend", "v3_control_cierres.html");
const html = fs.readFileSync(HTML_PATH, "utf-8");

let failures = 0;
let passed = 0;
function ok(cond, label) {
  if (cond) { passed++; console.log("  PASS -", label); }
  else { failures++; console.log("  FAIL -", label); }
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitFor(fn, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < (timeoutMs || 3000)) {
    if (fn()) return true;
    await sleep(20);
  }
  return false;
}

function makeDom(url) {
  const dom = new JSDOM(html, { runScripts: "dangerously", resources: "usable", url: url });
  return dom;
}

// ---------------------------------------------------------------------------
// Escenario 9: ?demo=1 nunca llama al backend.
// ---------------------------------------------------------------------------
async function test_demo_no_llama_backend() {
  console.log("\n[9] ?demo=1 nunca llama al backend");
  const dom = makeDom("http://localhost/v3_control_cierres.html?demo=1");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  let fetchCalls = 0;
  window.fetch = function () { fetchCalls++; return Promise.reject(new Error("fetch NO debería llamarse en modo demo")); };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelectorAll("#tabla-body tr[data-hash]").length === 5, 6000);

  const filas = window.document.querySelectorAll("#tabla-body tr");
  ok(fetchCalls === 0, "cero llamadas a fetch durante todo el ciclo demo");
  ok(filas.length === 5, "la tabla demo muestra las 5 filas sintéticas (" + filas.length + ")");
  ok(window.document.getElementById("demo-banner").style.display === "block", "banner de demo visible");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Escenario 1: procesar rango válido (real) -> tabla con el cierre LISTO.
// ---------------------------------------------------------------------------
async function test_procesar_rango_valido() {
  console.log("\n[1] Procesar rango válido (real)");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const calls = [];
  let estadoCall = 0;
  window.fetch = function (url, opts) {
    calls.push({ url: url, opts: opts });
    if (url.indexOf("/procesar") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-1", estado_lote: "PROCESANDO" }) });
    }
    if (url.indexOf("/estado") !== -1) {
      estadoCall++;
      var estado = estadoCall < 2 ? "PROCESANDO" : "LISTO_PARA_REVISION_O_PUBLICACION";
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-1", estado_lote: estado, total_cierres: 1, listos: 1, en_revision: 0 }) });
    }
    if (url.indexOf("/datos") !== -1) {
      return Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve({
          resultado: "OK", lote_id: "lote-1", cierres: [{
            fecha: "2026-09-01", archivo_esperado: "CIERRE 01-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR",
            diferencia: "0.00", bloqueadores: 0, ruta_sap: "/dev/salidas/SAP_01-09-2026.xlsx",
            requiere_revision: false, publicable: true, publicado: false, mensajes: ["Motor ejecutado: OK."],
          }],
        }),
      });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("in-fecha-desde").value = "2026-09-01";
  window.document.getElementById("in-fecha-hasta").value = "2026-09-01";
  window.document.getElementById("btn-procesar").click();

  await waitFor(() => window.document.querySelectorAll("#tabla-body tr[data-hash]").length === 1, 5000);
  const procesarCall = calls.find((c) => c.url.indexOf("/procesar") !== -1);
  ok(!!procesarCall, "se llamó a POST /webhook/tiq-v3-dev/procesar");
  const body = procesarCall ? JSON.parse(procesarCall.opts.body) : {};
  ok(body.fecha_inicio === "2026-09-01" && body.fecha_fin === "2026-09-01" && !!body.usuario_auditor, "body de /procesar trae fecha_inicio/fecha_fin/usuario_auditor");
  ok(body.caja === "tiquipaya", "body de /procesar trae caja='tiquipaya' por default (" + body.caja + ")");
  ok(calls.some((c) => c.url.indexOf("/estado?lote_id=lote-1") !== -1), "se hizo polling de /estado con el lote_id devuelto");
  ok(calls.some((c) => c.url.indexOf("/datos?lote_id=lote-1") !== -1), "se pidió /datos tras estado_lote != PROCESANDO");
  const fila = window.document.querySelector("#tabla-body tr");
  ok(fila && fila.textContent.indexOf("Listo") !== -1, "la fila muestra el estado LISTO_PARA_PUBLICAR");
  ok(fila && fila.querySelector("button.publicar") !== null, "aparece boton Publicar para el cierre habilitado");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Caja América: selector visible con TIQUIPAYA/AMERICA (default TIQUIPAYA),
// crear lote manda la caja elegida, y tras crear el lote esa identidad
// queda bloqueada (no se puede cambiar) para el resto de acciones del lote.
// ---------------------------------------------------------------------------
async function test_selector_caja_opciones_y_default() {
  console.log("\n[CAJA] El selector tiene TIQUIPAYA/AMERICA con default TIQUIPAYA");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.fetch = function () { return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }); };
  await waitFor(() => window.document.getElementById("in-caja"));
  const sel = window.document.getElementById("in-caja");
  const valores = Array.prototype.map.call(sel.options, (o) => o.value).sort();
  ok(valores.length === 2 && valores[0] === "america" && valores[1] === "tiquipaya", "opciones exactas: america, tiquipaya (" + valores.join(",") + ")");
  ok(sel.value === "tiquipaya", "valor por default es tiquipaya (" + sel.value + ")");
  ok(sel.disabled === false, "el selector empieza habilitado (sin lote creado todavía)");
  await sleep(50);
  dom.window.close();
}

async function test_crear_lote_america_manda_caja_america() {
  console.log("\n[CAJA] Crear lote con AMERICA manda caja='america'");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const calls = [];
  window.fetch = function (url, opts) {
    calls.push({ url: url, opts: opts });
    if (url.indexOf("/procesar") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-ame-1", estado_lote: "PROCESANDO", caja: "america" }) });
    }
    if (url.indexOf("/estado") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-ame-1", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    }
    if (url.indexOf("/datos") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-ame-1", cierres: [] }) });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-caja"));
  window.document.getElementById("in-fecha-desde").value = "2026-09-01";
  window.document.getElementById("in-fecha-hasta").value = "2026-09-01";
  window.document.getElementById("in-caja").value = "america";
  window.document.getElementById("btn-procesar").click();

  await waitFor(() => calls.some((c) => c.url.indexOf("/datos") !== -1), 5000);
  const procesarCall = calls.find((c) => c.url.indexOf("/procesar") !== -1);
  const body = procesarCall ? JSON.parse(procesarCall.opts.body) : {};
  ok(body.caja === "america", "body de /procesar trae caja='america' (" + body.caja + ")");

  await waitFor(() => window.document.getElementById("in-caja").disabled === true, 3000);
  const sel = window.document.getElementById("in-caja");
  const info = window.document.getElementById("caja-lote-info");
  ok(sel.disabled === true, "el selector se bloquea tras crear el lote");
  ok(sel.value === "america", "el selector queda fijado en la caja persistida por el backend");
  ok(info && info.textContent.indexOf("AMERICA") !== -1, "se muestra la caja asociada al lote (" + (info && info.textContent) + ")");
  await sleep(50);
  dom.window.close();
}

async function test_acciones_posteriores_no_mandan_ni_cambian_caja() {
  console.log("\n[CAJA] revisar/corregir/publicar no mandan `caja` ni permiten cambiarla");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.confirm = function () { return true; };
  const calls = [];
  window.fetch = function (url, opts) {
    calls.push({ url: url, opts: opts });
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-ame-2", estado_lote: "PROCESANDO", caja: "america" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{ fecha: "2026-09-01", archivo_esperado: "CIERRE 01-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR", requiere_revision: false, publicado: false, mensajes: [] }],
      }),
    });
    if (url.indexOf("/publicar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", publicados: [{ fecha: "2026-09-01", estado_publicacion: "PUBLICADO", publicado: true }], omitidos: [] }) });
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-caja"));
  window.document.getElementById("in-caja").value = "america";
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelectorAll("#tabla-body tr[data-hash] button.publicar").length === 1, 5000);

  // Manipular el DOM del selector (ya deshabilitado) nunca debe colarse en un
  // request posterior: publicar/corregir dependen solo de lote_id/fecha.
  window.document.getElementById("btn-recargar"); // noop, solo confirma que el DOM sigue vivo
  window.document.querySelector("#tabla-body tr[data-hash] button.publicar").click();
  await waitFor(() => calls.some((c) => c.url.indexOf("/publicar") !== -1), 3000);

  const publicarCall = calls.find((c) => c.url.indexOf("/publicar") !== -1);
  const bodyPublicar = JSON.parse(publicarCall.opts.body);
  ok(!("caja" in bodyPublicar), "el body de /publicar NO trae `caja`");
  ok(window.document.getElementById("in-caja").disabled === true, "el selector sigue bloqueado durante el ciclo de vida del lote");
  await sleep(50);
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Escenario 2: rango con SIN_ARCHIVO -> fila sin boton Publicar.
// ---------------------------------------------------------------------------
async function test_sin_archivo() {
  console.log("\n[2] Rango con SIN_ARCHIVO");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-2", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{ fecha: "2026-09-02", archivo_esperado: "CIERRE 02-09-2026.xlsm", estado_final: "SIN_ARCHIVO", requiere_revision: false, publicado: false, mensajes: [] }],
      }),
    });
    return Promise.reject(new Error("URL no esperada: " + url));
  };
  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  const fila = window.document.querySelector("#tabla-body tr");
  ok(fila && fila.textContent.indexOf("Faltante") !== -1, "la fila muestra el estado SIN_ARCHIVO (Faltante)");
  ok(fila && fila.querySelector("button.publicar") === null, "SIN_ARCHIVO nunca ofrece boton Publicar");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Escenario 3/4/5: cierre ERROR_REVISAR -> abrir detalle -> formulario de
// corrección solo ofrece campos reales, nunca "importe" -> enviar corrección
// válida (llama /corregir con el payload correcto, SIN sha256/version) ->
// enviar corrección de importe queda IMPOSIBLE de construir desde la UI.
// ---------------------------------------------------------------------------
async function test_revision_y_correccion() {
  console.log("\n[3,4,5] ERROR_REVISAR -> detalle -> corrección");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const calls = [];
  window.fetch = function (url, opts) {
    calls.push({ url: url, opts: opts });
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-3", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{
          fecha: "2026-09-03", archivo_esperado: "CIERRE 03-09-2026.xlsm", estado_final: "ERROR_REVISAR",
          requiere_revision: true, resultado_reproceso: null, publicado: false, diferencia: "100.00", bloqueadores: 1,
          mensajes: ["Cierre requiere revisión/corrección del auditor antes de poder publicarse."],
        }],
      }),
    });
    if (url.indexOf("/revisar") !== -1) {
      return Promise.resolve({
        ok: true, json: () => Promise.resolve({
          resultado: "OK", fecha: "2026-09-03", estado_final: "ERROR_REVISAR", requiere_revision: true,
          mensaje: "Cierre requiere revisión.", excepciones: [{
            categoria: "COMUNICACION_INTERNA", tipo: "CI_ASIGNACION_FALTANTE", sfc: "SFC101", factura: "F-1",
            cuenta_contable: "210201005", asignacion: null, motivo_legible: "Comunicación interna sin asignación",
            // AJUSTE UX: el backend (v3/dev_api._campos_aplicables) calcula
            // en Python cuál campo corresponde al problema REAL de ESTA
            // excepción (aquí, solo "asignacion" -- cuenta_contable ya está
            // presente); el frontend nunca decide esto.
            campos_corregibles_aplicables: ["asignacion"],
          }],
          campos_corregibles: { COMUNICACION_INTERNA: ["asignacion", "cuenta_contable"], VOUCHER: ["codigo_informado"], ATC: ["comision_asignacion", "comision_cuenta_contable", "neto_asignacion", "neto_cuenta_contable"] },
        }),
      });
    }
    if (url.indexOf("/corregir") !== -1) {
      return Promise.resolve({
        ok: true, json: () => Promise.resolve({
          resultado: "OK", cierre: {
            fecha: "2026-09-03", archivo_esperado: "CIERRE 03-09-2026.xlsm", estado_final: "ERROR_REVISAR",
            requiere_revision: true, resultado_reproceso: "LISTO_PARA_PUBLICAR", correccion_aplicada: true,
            publicado: false, diferencia: "0.00", bloqueadores: 0, mensaje: "Corrección aplicada y reprocesada: LISTO_PARA_PUBLICAR.", mensajes: [],
          },
        }),
      });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);

  window.document.querySelector("#tabla-body tr").click(); // abrir detalle -> dispara /revisar
  await waitFor(() => window.document.getElementById("sel-campo"), 3000);

  const selCampo = window.document.getElementById("sel-campo");
  const opciones = Array.from(selCampo.options).map((o) => o.value);
  ok(opciones.indexOf("importe") === -1, "el select de campo NUNCA ofrece 'importe' (" + opciones.join(",") + ")");
  ok(opciones.indexOf("asignacion") !== -1, "el select SI ofrece 'asignacion' (campo real aplicable a ESTA excepción)");
  // AJUSTE UX: aunque "cuenta_contable" es un campo PERMITIDO para la
  // categoría COMUNICACION_INTERNA en general, esta excepción puntual ya
  // tiene cuenta_contable presente -- no es el problema real, así que no
  // debe ofrecerse (el backend no lo incluyó en campos_corregibles_aplicables).
  ok(opciones.indexOf("cuenta_contable") === -1, "el select NO ofrece 'cuenta_contable' cuando no es el problema real de esta excepción (" + opciones.join(",") + ")");

  // HALLAZGO 1 (prueba manual FASE 9), reproducción EXACTA del reporte:
  // COMUNICACION_INTERNA -> seleccionar excepción -> campo "asignacion" ->
  // nuevo valor -> enviar. Los identificadores (sfc/factura) NUNCA los
  // escribe el usuario: deben viajar automáticamente, tomados de la
  // excepción real seleccionada.
  selCampo.value = "asignacion";
  window.document.getElementById("in-valor-autorizado").value = "REF2-NUEVA";
  window.document.getElementById("in-motivo").value = "Asignación confirmada (test automatizado)";
  const btnEnviar = Array.from(window.document.querySelectorAll("button")).find((b) => b.textContent === "ENVIAR CORRECCIÓN");
  btnEnviar.click();

  await waitFor(() => calls.some((c) => c.url.indexOf("/corregir") !== -1), 3000);
  const corregirCall = calls.find((c) => c.url.indexOf("/corregir") !== -1);
  const bodyCorregir = JSON.parse(corregirCall.opts.body);
  ok(bodyCorregir.correccion.campo_corregido === "asignacion", "el body de /corregir usa el campo elegido (asignacion)");
  ok(bodyCorregir.correccion.valor_autorizado === "REF2-NUEVA", "el body de /corregir lleva el valor autorizado ingresado");
  ok(!!bodyCorregir.correccion.identificadores, "el body de /corregir incluye identificadores");
  ok(bodyCorregir.correccion.identificadores.sfc === "SFC101", "identificadores.sfc viaja automáticamente desde la excepción (nunca lo escribe el usuario)");
  ok(bodyCorregir.correccion.identificadores.factura === "F-1", "identificadores.factura viaja automáticamente desde la excepción (nunca lo escribe el usuario)");
  ok(!("sha256_origen" in bodyCorregir.correccion), "el frontend NUNCA envía sha256_origen (lo calcula el servidor)");
  ok(!("version_correccion" in bodyCorregir.correccion), "el frontend NUNCA envía version_correccion (lo calcula el servidor)");
  ok(!("importe" in bodyCorregir.correccion) || bodyCorregir.correccion.campo_corregido !== "importe", "nunca se envía una corrección de importe");

  await waitFor(() => window.document.querySelector(".form-ok"), 3000);
  ok(!!window.document.querySelector(".form-ok"), "el formulario muestra confirmación tras la corrección exitosa");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// AJUSTE UX: mostrar solo campos REALMENTE pendientes de corrección. El
// frontend NUNCA interpreta texto libre: solo renderiza exactamente
// exc.campos_corregibles_aplicables (calculado en Python). Con DOS
// excepciones simultáneas de distinto tipo, cada una debe aislar su propio
// campo real al cambiar la excepción seleccionada.
// ---------------------------------------------------------------------------
async function test_campos_aplicables_por_excepcion() {
  console.log("\n[AJUSTE UX] campos_corregibles_aplicables aísla el campo real por excepción");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = (m) => { window.__lastAlert = m; };
  const excAsignacion = {
    categoria: "COMUNICACION_INTERNA", tipo: "CI_ASIGNACION_FALTANTE", sfc: "SFC101", factura: "F-1",
    cuenta_contable: "210201005", asignacion: null, motivo_legible: "Comunicación interna sin asignación",
    campos_corregibles_aplicables: ["asignacion"],
  };
  const excCuenta = {
    categoria: "COMUNICACION_INTERNA", tipo: "CI_CUENTA_FALTANTE", sfc: "SFC101", factura: "F-2",
    cuenta_contable: null, asignacion: "REF2", motivo_legible: "Comunicación interna sin cuenta contable asignada",
    campos_corregibles_aplicables: ["cuenta_contable"],
  };
  const { fetchImpl } = _mockComunPostCorreccion("2026-09-08", [{
    resultado: "OK", fecha: "2026-09-08", estado_final: "ERROR_REVISAR", requiere_revision: true, mensaje: "...",
    diferencia: "100.00", bloqueadores: 2, excepciones: [excAsignacion, excCuenta],
    campos_corregibles: { COMUNICACION_INTERNA: ["asignacion", "cuenta_contable"] },
  }], { resultado: "OK", cierre: {} });
  window.fetch = fetchImpl;

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  window.document.querySelector("#tabla-body tr[data-hash]").click();
  await waitFor(() => window.document.getElementById("sel-campo"), 3000);

  const selExcepcion = window.document.getElementById("sel-excepcion");
  const selCampo = window.document.getElementById("sel-campo");

  // primera excepción seleccionada por defecto (asignacion): SOLO asignacion.
  let opciones = Array.from(selCampo.options).map((o) => o.value);
  ok(opciones.length === 1 && opciones[0] === "asignacion", "excepción 1 (CI_ASIGNACION_FALTANTE) ofrece SOLO 'asignacion' (" + opciones.join(",") + ")");
  ok(opciones.indexOf("importe") === -1, "nunca se ofrece 'importe'");

  // cambiar a la segunda excepción (cuenta_contable): SOLO cuenta_contable,
  // nunca "asignacion" (que era el campo de la OTRA excepción).
  selExcepcion.value = "1";
  selExcepcion.dispatchEvent(new window.Event("change"));
  opciones = Array.from(selCampo.options).map((o) => o.value);
  ok(opciones.length === 1 && opciones[0] === "cuenta_contable", "excepción 2 (CI_CUENTA_FALTANTE) ofrece SOLO 'cuenta_contable' (" + opciones.join(",") + ")");
  ok(opciones.indexOf("asignacion") === -1, "el campo de la OTRA excepción (asignacion) no se filtra hacia esta");
  ok(opciones.indexOf("importe") === -1, "nunca se ofrece 'importe'");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// HALLAZGO (post-corrección): tras /corregir, el panel debe descartar el
// detalle de revisión anterior y pedir uno FRESCO — nunca mostrar la
// excepción ya resuelta ni un formulario obsoleto.
// ---------------------------------------------------------------------------

function _mockComunPostCorreccion(fecha, revisarResponses, corregirResponse) {
  const calls = [];
  let revisarCallCount = 0;
  const fetchImpl = function (url, opts) {
    calls.push({ url, opts });
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-x", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{ fecha, archivo_esperado: "CIERRE.xlsm", estado_final: "ERROR_REVISAR", requiere_revision: true, resultado_reproceso: null, publicado: false, diferencia: "100.00", bloqueadores: 1, mensajes: [] }],
      }),
    });
    if (url.indexOf("/revisar") !== -1) {
      const resp = revisarResponses[Math.min(revisarCallCount, revisarResponses.length - 1)];
      revisarCallCount++;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(resp) });
    }
    if (url.indexOf("/corregir") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve(corregirResponse) });
    return Promise.reject(new Error("URL no esperada: " + url));
  };
  return { calls, fetchImpl, getRevisarCallCount: () => revisarCallCount };
}

async function _enviarCorreccionDesdeForm(window) {
  await waitFor(() => window.document.getElementById("sel-campo"), 3000);
  window.document.getElementById("in-valor-autorizado").value = "210201005";
  window.document.getElementById("in-motivo").value = "test";
  const btnEnviar = Array.from(window.document.querySelectorAll("button")).find((b) => b.textContent === "ENVIAR CORRECCIÓN");
  btnEnviar.click();
  await waitFor(() => window.document.querySelector(".form-ok"), 3000);
}

// 1+2: excepción corregida desaparece + reproceso LISTO -> formulario
// desaparece y aparece PUBLICAR (banner de éxito, sin refetch innecesario).
async function test_post_correccion_reproceso_listo() {
  console.log("\n[Post-corrección A] Reproceso LISTO_PARA_PUBLICAR");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = (m) => { window.__lastAlert = m; };
  const excOriginal = { categoria: "COMUNICACION_INTERNA", tipo: "CI_CUENTA_FALTANTE", sfc: "SFC101", factura: "F-1", cuenta_contable: null, asignacion: "REF1", motivo_legible: "Sin cuenta contable", campos_corregibles_aplicables: ["cuenta_contable"] };
  const revisarOriginal = { resultado: "OK", fecha: "2026-09-05", estado_final: "ERROR_REVISAR", requiere_revision: true, mensaje: "...", diferencia: "100.00", bloqueadores: 1, excepciones: [excOriginal], campos_corregibles: { COMUNICACION_INTERNA: ["asignacion", "cuenta_contable"] } };
  const { fetchImpl, getRevisarCallCount } = _mockComunPostCorreccion("2026-09-05", [revisarOriginal], {
    resultado: "OK", cierre: {
      fecha: "2026-09-05", archivo_esperado: "CIERRE.xlsm", estado_final: "ERROR_REVISAR", requiere_revision: true,
      correccion_aplicada: true, resultado_reproceso: "LISTO_PARA_PUBLICAR", diferencia: "0.00", bloqueadores: 0,
      publicado: false, mensaje: "Corrección aplicada y reprocesada: LISTO_PARA_PUBLICAR.", mensajes: [],
    },
  });
  window.fetch = fetchImpl;

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  window.document.querySelector("#tabla-body tr[data-hash]").click();
  await _enviarCorreccionDesdeForm(window);

  await waitFor(() => window.document.getElementById("detalle-body").textContent.indexOf("REPROCESO EXITOSO") !== -1, 3000);
  const texto = window.document.getElementById("detalle-body").textContent;
  ok(texto.indexOf("REPROCESO EXITOSO") !== -1, "banner muestra REPROCESO EXITOSO");
  ok(texto.indexOf("LISTO PARA PUBLICAR") !== -1, "banner indica LISTO PARA PUBLICAR");
  ok(window.document.getElementById("sel-excepcion") === null, "el formulario de corrección desaparece (excepción ya no visible)");
  ok(!!Array.from(window.document.querySelectorAll("#detalle-body button")).find((b) => b.textContent.indexOf("PUBLICAR ESTE CIERRE") !== -1), "aparece el botón PUBLICAR");
  ok(getRevisarCallCount() === 1, "no se repite /revisar innecesariamente cuando el reproceso ya quedó LISTO (" + getRevisarCallCount() + " llamada(s))");
  dom.window.close();
}

// 3+6: reproceso ERROR_REVISAR con OTRA excepción -> se pide /revisar de
// nuevo (POST-REPROCESO, nunca datos viejos) y se muestra SOLO la nueva.
async function test_post_correccion_reproceso_con_nueva_excepcion() {
  console.log("\n[Post-corrección B] Reproceso ERROR_REVISAR con nueva excepción");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = (m) => { window.__lastAlert = m; };
  const excOriginal = { categoria: "COMUNICACION_INTERNA", tipo: "CI_CUENTA_FALTANTE", sfc: "SFC101", factura: "F-1", cuenta_contable: null, asignacion: "REF1", motivo_legible: "MOTIVO_ORIGINAL_DEBE_DESAPARECER", campos_corregibles_aplicables: ["cuenta_contable"] };
  const excNueva = { categoria: "VOUCHER", tipo: "POSIBLE_TYPO", sfc: "SFC102", codigo_informado: "VCH999", motivo_legible: "MOTIVO_NUEVO_POST_REPROCESO", campos_corregibles_aplicables: ["codigo_informado"] };
  const revisarOriginal = { resultado: "OK", fecha: "2026-09-05", estado_final: "ERROR_REVISAR", requiere_revision: true, mensaje: "...", diferencia: "100.00", bloqueadores: 1, excepciones: [excOriginal], campos_corregibles: { COMUNICACION_INTERNA: ["asignacion", "cuenta_contable"], VOUCHER: ["codigo_informado"] } };
  const revisarPostReproceso = { resultado: "OK", fecha: "2026-09-05", estado_final: "ERROR_REVISAR", requiere_revision: true, mensaje: "...", diferencia: "50.00", bloqueadores: 1, excepciones: [excNueva], campos_corregibles: { COMUNICACION_INTERNA: ["asignacion", "cuenta_contable"], VOUCHER: ["codigo_informado"] } };
  const { fetchImpl, getRevisarCallCount } = _mockComunPostCorreccion("2026-09-05", [revisarOriginal, revisarPostReproceso], {
    resultado: "OK", cierre: {
      fecha: "2026-09-05", archivo_esperado: "CIERRE.xlsm", estado_final: "ERROR_REVISAR", requiere_revision: true,
      correccion_aplicada: true, resultado_reproceso: "ERROR_REVISAR", diferencia: "50.00", bloqueadores: 1,
      publicado: false, mensaje: "Corrección aplicada y reprocesada: ERROR_REVISAR.", mensajes: [],
    },
  });
  window.fetch = fetchImpl;

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  window.document.querySelector("#tabla-body tr[data-hash]").click();
  await _enviarCorreccionDesdeForm(window);

  await waitFor(() => getRevisarCallCount() === 2, 3000);
  await waitFor(() => window.document.getElementById("sel-excepcion") && window.document.getElementById("sel-excepcion").textContent.indexOf("MOTIVO_NUEVO_POST_REPROCESO") !== -1, 3000);
  const opcionesTexto = window.document.getElementById("sel-excepcion").textContent;
  ok(opcionesTexto.indexOf("MOTIVO_NUEVO_POST_REPROCESO") !== -1, "el formulario muestra la NUEVA excepción post-reproceso");
  ok(opcionesTexto.indexOf("MOTIVO_ORIGINAL_DEBE_DESAPARECER") === -1, "la excepción YA CORREGIDA/original desaparece del formulario (no quedan datos obsoletos)");
  ok(getRevisarCallCount() === 2, "se pidió un /revisar FRESCO tras la corrección, no se reutilizó el anterior (" + getRevisarCallCount() + " llamadas)");
  dom.window.close();
}

// 4+5: reproceso ERROR_REVISAR sin excepciones estructuradas (CASO C) -> no
// aparece el formulario, se muestra el mensaje "sin corrección autorizada"
// con el cuadre detallado.
async function test_post_correccion_reproceso_sin_excepciones() {
  console.log("\n[Post-corrección C] Reproceso ERROR_REVISAR sin excepciones corregibles");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = (m) => { window.__lastAlert = m; };
  const excOriginal = { categoria: "COMUNICACION_INTERNA", tipo: "CI_CUENTA_FALTANTE", sfc: "SFC101", factura: "F-1", cuenta_contable: null, asignacion: "REF1", motivo_legible: "MOTIVO_ORIGINAL_DEBE_DESAPARECER", campos_corregibles_aplicables: ["cuenta_contable"] };
  const revisarOriginal = { resultado: "OK", fecha: "2026-09-05", estado_final: "ERROR_REVISAR", requiere_revision: true, mensaje: "...", diferencia: "100.00", bloqueadores: 1, excepciones: [excOriginal], campos_corregibles: { COMUNICACION_INTERNA: ["asignacion", "cuenta_contable"] } };
  const revisarPostReproceso = {
    resultado: "OK", fecha: "2026-09-05", estado_final: "ERROR_REVISAR", requiere_revision: true, mensaje: "...",
    diferencia: "50.00", bloqueadores: 1, excepciones: [], campos_corregibles: {},
    cuadre: { universo_original: "500.00", alquileres: "0.00", universo_ajustado: "500.00", total_vouchers: "200.00", cantidad_vouchers: 2, total_ci: "250.00", cantidad_ci: 3, atc_bruto: "50.00", atc_neto: "48.00", atc_comision: "2.00" },
  };
  const { fetchImpl, getRevisarCallCount } = _mockComunPostCorreccion("2026-09-05", [revisarOriginal, revisarPostReproceso], {
    resultado: "OK", cierre: {
      fecha: "2026-09-05", archivo_esperado: "CIERRE.xlsm", estado_final: "ERROR_REVISAR", requiere_revision: true,
      correccion_aplicada: true, resultado_reproceso: "ERROR_REVISAR", diferencia: "50.00", bloqueadores: 1,
      publicado: false, mensaje: "Corrección aplicada y reprocesada: ERROR_REVISAR.", mensajes: [],
    },
  });
  window.fetch = fetchImpl;

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  window.document.querySelector("#tabla-body tr[data-hash]").click();
  await _enviarCorreccionDesdeForm(window);

  await waitFor(() => getRevisarCallCount() === 2, 3000);
  await waitFor(() => window.document.getElementById("detalle-body").textContent.indexOf("SIN CORRECCIÓN AUTORIZADA") !== -1, 3000);
  const texto = window.document.getElementById("detalle-body").textContent;
  ok(window.document.getElementById("sel-excepcion") === null, "no aparece el formulario de corrección (sin excepciones corregibles)");
  ok(texto.indexOf("SIN CORRECCIÓN AUTORIZADA") !== -1, "se muestra el mensaje 'sin corrección autorizada'");
  ok(texto.indexOf("no pueden modificarse") !== -1, "se aclara que los importes no pueden modificarse");
  ok(texto.indexOf("MOTIVO_ORIGINAL_DEBE_DESAPARECER") === -1, "no queda rastro de la excepción original ya resuelta");
  ok(texto.indexOf("500.00") !== -1 || texto.indexOf("Bs 500,00") !== -1, "se muestra el cuadre detallado real (universo_ajustado)");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Escenario 6/7: publicación válida + publicación repetida idempotente.
// ---------------------------------------------------------------------------
async function test_publicacion() {
  console.log("\n[6,7] Publicación válida + repetida (idempotente)");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.confirm = function () { return true; }; // FASE 11A.1: confirma la publicación
  const calls = [];
  let publicarCalls = 0;
  window.fetch = function (url, opts) {
    calls.push({ url: url, opts: opts });
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-4", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION", publication_mode: "dev" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{ fecha: "2026-09-04", archivo_esperado: "CIERRE 04-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR", requiere_revision: false, publicado: false, mensajes: [] }],
      }),
    });
    if (url.indexOf("/publicar") !== -1) {
      publicarCalls++;
      var publicado = publicarCalls >= 1;
      var estadoPub = publicarCalls === 1 ? "PUBLICADO" : "YA_PUBLICADO";
      return Promise.resolve({
        ok: true, json: () => Promise.resolve({
          resultado: "OK", publicados: [{
            fecha: "2026-09-04", archivo_esperado: "CIERRE 04-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR",
            requiere_revision: false, publicado: publicado, estado_publicacion: estadoPub, sha256: "abc123", ruta_marker: "/dev/publicacion/markers/PROCESADO_abc123.json", mensajes: [],
          }], omitidos: [],
        }),
      });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash] button.publicar"), 5000);

  window.document.querySelector("#tabla-body tr[data-hash] button.publicar").click();
  await waitFor(() => publicarCalls === 1 && window.document.querySelector(".badge-publicado"), 3000);
  ok(!!window.document.querySelector(".badge-publicado"), "tras publicar, la fila muestra el badge 'Publicado'");
  ok(window.document.querySelector("#tabla-body button.publicar") === null, "ya no se ofrece el boton Publicar para un cierre ya publicado");
  ok(publicarCalls === 1, "confirmar la publicación dispara EXACTAMENTE una llamada a /publicar (" + publicarCalls + ")");

  // Segunda publicación (idempotente): se simula reenviando la misma acción
  // directamente contra el backend (no hay boton visible ya) para confirmar
  // que el backend (mock) devuelve YA_PUBLICADO sin duplicar nada.
  const resp2 = await window.fetch("/webhook/tiq-v3-dev/publicar", { method: "POST", body: JSON.stringify({ lote_id: "lote-4", fechas: ["2026-09-04"] }) }).then((r) => r.json());
  ok(resp2.publicados[0].estado_publicacion === "YA_PUBLICADO", "una segunda publicación del mismo cierre responde YA_PUBLICADO (idempotente)");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// HALLAZGO 2 (prueba manual FASE 9), reproducción EXACTA del reporte: un
// cierre que YA tenía PROCESADO_<SHA256>.json de una corrida DEV anterior
// (estado_publicacion:"YA_PUBLICADO" desde el primer /datos, ANTES de que
// el usuario haga ningún clic en esta sesión) NO debe ofrecer el botón
// activo "PUBLICAR ESTE CIERRE"; y si de todos modos se reintenta publicar
// varias veces, el historial mostrado no debe acumular copias del mismo
// mensaje idempotente.
// ---------------------------------------------------------------------------
async function test_cierre_ya_publicado_no_ofrece_boton_ni_infla_historial() {
  console.log("\n[Hallazgo 2] Cierre ya publicado: sin botón activo, historial no crece");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const mensajeIdempotente = "Marcador ya existente en publicacion/markers/: no se republica (idempotencia SHA256).";
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-6", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION", publication_mode: "dev" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{
          fecha: "2026-09-01", archivo_esperado: "CIERRE 01-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR",
          requiere_revision: false, publicado: false, estado_publicacion: "YA_PUBLICADO", sha256: "abc123",
          ruta_marker: "/dev/publicacion/markers/PROCESADO_abc123.json",
          mensajes: ["Motor ejecutado: OK.", "Cierre cuadrado y validado: listo para publicar (aún no publicado).", mensajeIdempotente],
        }],
      }),
    });
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);

  ok(window.document.querySelector("#tabla-body tr[data-hash] button.publicar") === null, "un cierre YA_PUBLICADO (de una corrida previa) NUNCA muestra el botón activo, ni siquiera antes del primer clic de esta sesión");
  ok(!!window.document.querySelector(".badge-publicado"), "la fila muestra el badge 'Publicado' para un cierre YA_PUBLICADO");

  window.document.querySelector("#tabla-body tr[data-hash]").click(); // abrir detalle
  await waitFor(() => window.document.getElementById("detalle-body").textContent.indexOf("PUBLICADO") !== -1, 3000);
  ok(window.document.getElementById("detalle-body").textContent.indexOf("YA PUBLICADO") !== -1, "el panel de detalle muestra 'YA PUBLICADO', no un botón activo");
  ok(!Array.from(window.document.querySelectorAll("#detalle-body button")).some((b) => b.textContent.indexOf("PUBLICAR ESTE CIERRE") !== -1), "el panel de detalle NO ofrece 'PUBLICAR ESTE CIERRE' para un cierre ya publicado");

  const ocurrenciasHistorial = (window.document.getElementById("detalle-body").textContent.match(new RegExp(mensajeIdempotente.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length;
  ok(ocurrenciasHistorial === 1, "el mensaje idempotente aparece UNA sola vez en el historial mostrado (" + ocurrenciasHistorial + ")");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Escenario 8: error de backend mostrado correctamente (nunca falla en silencio).
// ---------------------------------------------------------------------------
async function test_error_backend() {
  console.log("\n[8] Error de backend mostrado correctamente");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  let alertMsg = null;
  window.alert = function (msg) { alertMsg = msg; };
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) {
      return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ resultado: "ERROR", mensaje: "LOTE_NO_ENCONTRADO: fallo simulado" }) });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };
  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => alertMsg !== null, 3000);
  ok(alertMsg !== null && alertMsg.indexOf("fallo simulado") !== -1, "el error del backend se muestra al usuario (alert): " + JSON.stringify(alertMsg));
  ok(window.document.getElementById("btn-procesar").disabled === false, "el boton PROCESAR se reactiva tras el error (no queda bloqueado)");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// Escenario 10: frontend no permite publicar un cierre no habilitado (no
// renderiza el boton; y el backend, autoridad final, lo confirma en test_dev_api.py).
// ---------------------------------------------------------------------------
async function test_no_publicar_no_habilitado() {
  console.log("\n[10] Frontend no ofrece publicar un cierre no habilitado");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-5", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [
          { fecha: "2026-09-06", archivo_esperado: "CIERRE 06-09-2026.xlsm", estado_final: "ERROR_TECNICO", requiere_revision: false, publicado: false, mensajes: [] },
          { fecha: "2026-09-07", archivo_esperado: "CIERRE 07-09-2026.xlsm", estado_final: "ERROR_REVISAR", requiere_revision: true, resultado_reproceso: null, publicado: false, mensajes: [] },
        ],
      }),
    });
    return Promise.reject(new Error("URL no esperada: " + url));
  };
  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelectorAll("#tabla-body tr[data-hash]").length === 2, 5000);
  ok(window.document.querySelectorAll("#tabla-body button.publicar").length === 0, "ningún cierre no-publicable (ERROR_TECNICO/ERROR_REVISAR) muestra boton Publicar");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// FASE 10C: precheck de cobertura del maestro. BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA
// es una precondicion de ENTORNO, nunca un error contable del cierre: la
// tabla debe mostrar un tag/etiqueta DISTINTO de "revisar"/"error", el panel
// de detalle debe mostrar la cobertura real (MACROS/ATC) y el mensaje de
// verificacion, y NUNCA debe ofrecerse el formulario de correccion ni el
// boton Publicar para este cierre.
// ---------------------------------------------------------------------------
async function test_maestro_sin_cobertura_no_ofrece_correccion_ni_publicacion() {
  console.log("\n[FASE 10C] MAESTRO SIN COBERTURA CONFIRMADA: sin correccion ni publicacion");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-precheck", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{
          fecha: "2026-09-11", archivo_esperado: "CIERRE 11-09-2026.xlsm",
          estado_final: "BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA",
          estado_precheck_maestro: "BLOQUEADO_MAESTRO_COBERTURA_NO_CONFIRMADA",
          fecha_maxima_macros: "2026-09-10", fecha_maxima_atc: "2026-09-10",
          requiere_revision: false, publicable: false, publicado: false,
          diferencia: null, bloqueadores: null,
          mensaje: "El maestro mensual no tiene cobertura confirmada hasta la fecha de este cierre.",
          mensajes: ["El maestro mensual no tiene cobertura confirmada hasta la fecha de este cierre."],
        }],
      }),
    });
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);

  const tag = window.document.querySelector("#tabla-body .tag");
  ok(!!tag && tag.classList.contains("bloqueo-maestro"), "la fila usa un tag distinto (bloqueo-maestro), nunca 'revisar' ni 'error'");
  ok(!tag.classList.contains("revisar") && !tag.classList.contains("error"), "el tag NUNCA se confunde con revision/error contable");
  ok(window.document.querySelectorAll("#tabla-body button.publicar").length === 0, "no se ofrece boton Publicar en la fila");

  window.document.querySelector("#tabla-body tr[data-hash]").click();
  await waitFor(() => window.document.getElementById("detalle-body").textContent.indexOf("MAESTRO SIN COBERTURA CONFIRMADA") !== -1, 3000);
  const texto = window.document.getElementById("detalle-body").textContent;
  ok(texto.indexOf("MAESTRO SIN COBERTURA CONFIRMADA") !== -1, "el panel de detalle muestra el aviso de cobertura no confirmada");
  ok(texto.indexOf("2026-09-10") !== -1, "el panel muestra hasta donde llega la cobertura real (MACROS/ATC)");
  ok(texto.indexOf("Verifique o actualice el maestro") !== -1, "el panel muestra el mensaje de verificacion pedido");
  ok(window.document.getElementById("sel-excepcion") === null, "NUNCA se ofrece el formulario de correccion para este bloqueo");
  ok(!Array.from(window.document.querySelectorAll("#detalle-body button")).some((b) => b.textContent.indexOf("PUBLICAR") !== -1), "NUNCA se ofrece el boton Publicar en el detalle");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// FASE 10F: ajustes de interfaz. Banner tecnico "MODO REAL" eliminado (con
// indicador pequeño "ENTORNO: DEV" en cabecera), texto residual "(modo
// demo)" corregido en modo real, panel Cuadre con datos reales (Universo/
// Recaudación explicada/Diferencia) sin "N/D" cuando existen, y sin
// referencias "(demo)" en cierres reales (Hash origen).
// ---------------------------------------------------------------------------
async function test_ajustes_interfaz_fase_10f() {
  console.log("\n[FASE 10F] Banner tecnico eliminado, cuadre real, sin residuos demo");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-10f", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{
          fecha: "2026-09-10", archivo_esperado: "CIERRE 10-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR",
          diferencia: "0.00", bloqueadores: 0, requiere_revision: false, publicable: true, publicado: false,
          sha256: null, mensajes: ["Motor ejecutado: OK."],
          cuadre: { universo_ajustado: "1500.00", recaudacion_explicada: "1500.00", diferencia: "0.00" },
        }],
      }),
    });
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  // el banner tecnico "MODO REAL" ya no existe en el DOM
  ok(window.document.getElementById("real-banner") === null, "el banner tecnico #real-banner fue eliminado");
  // FASE 11A.1: indicador pequeño de entorno en cabecera -- con 06B ya
  // enganchado en /publicar (PUBLICACION_OFICIAL=true), debe avisar
  // "PUBLICACIÓN: OFICIAL", nunca "ENTORNO: DEV" (evita que alguien crea
  // que sigue en DEV cuando el boton ya escribe Drive). Se actualiza en
  // DOMContentLoaded: hay que esperarlo antes de leerlo.
  await waitFor(() => window.document.getElementById("badge-entorno") && window.document.getElementById("badge-entorno").className === "badge-oficial", 3000);
  const badge = window.document.getElementById("badge-entorno");
  ok(!!badge && badge.textContent.indexOf("PUBLICACIÓN: OFICIAL") !== -1, "aparece el indicador 'PUBLICACIÓN: OFICIAL' en cabecera");
  ok(badge.className === "badge-oficial", "el badge de entorno usa el estilo distintivo 'badge-oficial', nunca el de DEV");

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  // texto residual sin "(modo demo)" en modo real, desde el primer render
  ok(window.document.getElementById("tabla-body").textContent.indexOf("(modo demo)") === -1, "el placeholder inicial en modo real NO dice '(modo demo)'");
  ok(window.document.getElementById("tabla-body").textContent.indexOf("Pulsa") !== -1, "el placeholder sigue invitando a procesar");

  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  window.document.querySelector("#tabla-body tr[data-hash]").click();
  await waitFor(() => window.document.getElementById("detalle-body").textContent.indexOf("Cuadre") !== -1, 3000);

  const texto = window.document.getElementById("detalle-body").textContent;
  ok(texto.indexOf("N/D") === -1 || texto.indexOf("Bs 1.500,00") !== -1, "el cuadre real (Universo/Recaudación) se muestra, no N/D, cuando el dato existe");
  ok(texto.indexOf("(demo)") === -1, "ninguna referencia '(demo)' aparece en un cierre real");
  ok(texto.indexOf("Hash origen") !== -1 && texto.indexOf("N/D (demo)") === -1, "Hash origen ausente se muestra como N/D simple, sin '(demo)', en modo real");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// FASE 11A.1: cancelar la confirmación de publicación => cero llamadas a
// /publicar (el guard de confirmación corta ANTES de tocar la red).
// ---------------------------------------------------------------------------
async function test_cancelar_confirmacion_publicar_no_llama_backend() {
  console.log("\n[11A.1] Cancelar confirmación de PUBLICAR => cero llamadas a /publicar");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  let confirmMensaje = null;
  window.confirm = function (msg) { confirmMensaje = msg; return false; }; // el usuario cancela
  let publicarCalls = 0;
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-11a1", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{ fecha: "2026-09-10", archivo_esperado: "CIERRE 10-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR", requiere_revision: false, publicado: false, mensajes: [] }],
      }),
    });
    if (url.indexOf("/publicar") !== -1) { publicarCalls++; return Promise.reject(new Error("NUNCA debería llamarse /publicar tras cancelar la confirmación")); }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash] button.publicar"), 5000);

  window.document.querySelector("#tabla-body tr[data-hash] button.publicar").click();
  await sleep(50);

  ok(confirmMensaje !== null, "se mostró una confirmación antes de intentar publicar");
  ok(confirmMensaje.indexOf("10/09/2026") !== -1, "la confirmación menciona la fecha del cierre en formato DD/MM/AAAA");
  ok(/continuar/i.test(confirmMensaje), "la confirmación pregunta explícitamente si continuar");
  ok(publicarCalls === 0, "cancelar la confirmación produce CERO llamadas a /publicar (" + publicarCalls + ")");
  ok(window.document.querySelector("#tabla-body tr[data-hash] button.publicar") !== null, "el cierre sigue mostrando el botón Publicar (nada cambió)");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// FASE 11A.2: el frontend LEE publication_mode del backend (GET /estado),
// nunca lo decide con una constante propia. Dos escenarios: backend dice
// "dev" -> badge ENTORNO: DEV; backend dice "official" -> PUBLICACIÓN: OFICIAL.
// ---------------------------------------------------------------------------
async function test_publication_mode_dev_muestra_badge_dev() {
  console.log("\n[11A.2] Backend publication_mode='dev' => badge 'ENTORNO: DEV'");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  let estadoCalls = 0;
  window.fetch = function (url) {
    if (url.indexOf("/estado") !== -1) {
      estadoCalls++;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "ERROR", codigo: "LoteNoEncontradoError", mensaje: "sin lote todavia", publication_mode: "dev" }) });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => estadoCalls >= 1, 3000);
  await waitFor(() => window.document.getElementById("badge-entorno") && window.document.getElementById("badge-entorno").className === "badge-dev", 3000);
  const badge = window.document.getElementById("badge-entorno");
  ok(estadoCalls >= 1, "el frontend llamó a GET /estado al cargar la página para obtener publication_mode");
  ok(!!badge && badge.textContent.indexOf("ENTORNO: DEV") !== -1, "el badge muestra 'ENTORNO: DEV' cuando el backend responde publication_mode:'dev'");
  ok(badge.className === "badge-dev", "el badge usa el estilo 'badge-dev'");
  dom.window.close();
}

async function test_publication_mode_official_muestra_badge_oficial() {
  console.log("\n[11A.2] Backend publication_mode='official' => badge 'PUBLICACIÓN: OFICIAL'");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.fetch = function (url) {
    if (url.indexOf("/estado") !== -1) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "ERROR", codigo: "LoteNoEncontradoError", mensaje: "sin lote todavia", publication_mode: "official" }) });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };

  await waitFor(() => window.document.getElementById("badge-entorno") && window.document.getElementById("badge-entorno").className === "badge-oficial", 3000);
  const badge = window.document.getElementById("badge-entorno");
  ok(!!badge && badge.textContent.indexOf("PUBLICACIÓN: OFICIAL") !== -1, "el badge muestra 'PUBLICACIÓN: OFICIAL' cuando el backend responde publication_mode:'official'");
  ok(badge.className === "badge-oficial", "el badge usa el estilo 'badge-oficial'");
  dom.window.close();
}

async function test_publication_mode_demo_nunca_llama_backend() {
  console.log("\n[11A.2] ?demo=1: nunca se consulta publication_mode al backend");
  const dom = makeDom("http://localhost/v3_control_cierres.html?demo=1");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  let fetchCalls = 0;
  window.fetch = function () { fetchCalls++; return Promise.reject(new Error("fetch NO debería llamarse en modo demo")); };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  ok(fetchCalls === 0, "cero llamadas a fetch (ni siquiera para publication_mode) en modo demo");
  dom.window.close();
}

// ---------------------------------------------------------------------------
// FASE 12B — CIERRE MENSUAL (GLOBAL / CONTROL 1 / CONTROL 3). Botones
// separados del flujo diario: cada uno llama a SU endpoint exactamente una
// vez, y ninguno de los dos flujos dispara al otro.
// ---------------------------------------------------------------------------

function _mockFetchMensual(overrides) {
  const calls = { global: 0, control1: 0, control3: 0, estado: 0, otros: 0 };
  const bodies = { global: [], control1: [], control3: [] };
  const fn = function (url, opts) {
    if (url.indexOf("/global") !== -1) {
      calls.global++;
      if (opts && opts.body) bodies.global.push(JSON.parse(opts.body));
      return (overrides && overrides.global) || Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", estado: "VALIDADO_PENDIENTE_PUBLICACION", cantidad_sap_incluidos: 2, fechas_faltantes: [] }) });
    }
    if (url.indexOf("/control1") !== -1) {
      calls.control1++;
      if (opts && opts.body) bodies.control1.push(JSON.parse(opts.body));
      const ov1 = overrides && overrides.control1;
      if (typeof ov1 === "function") return ov1(calls.control1, opts);
      return ov1 || Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", estado: "OK_SIN_DUPLICADOS", filas_incorporadas_historico: 3 }) });
    }
    if (url.indexOf("/control3") !== -1) {
      calls.control3++;
      if (opts && opts.body) bodies.control3.push(JSON.parse(opts.body));
      const ov3 = overrides && overrides.control3;
      if (typeof ov3 === "function") return ov3(calls.control3, opts);
      return ov3 || Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "OK", estado: "OK", abiertas: 1, cerradas: 2, revisar: 0 }) });
    }
    if (url.indexOf("/estado") !== -1) {
      calls.estado++;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "ERROR", codigo: "LoteNoEncontradoError", publication_mode: "official" }) });
    }
    calls.otros++;
    return Promise.reject(new Error("URL no esperada: " + url));
  };
  return { fn, calls, bodies };
}

async function test_boton_global_llama_una_vez_y_muestra_resultado() {
  console.log("\n[12B] Botón GENERAR GLOBAL llama una vez (a /global, por caja) y muestra resultado claro");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const { fn, calls, bodies } = _mockFetchMensual();
  window.fetch = fn;

  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-global").click();
  await waitFor(() => window.document.getElementById("mensual-resultado").className.indexOf("ok") !== -1
    || window.document.getElementById("mensual-resultado").className.indexOf("error") !== -1, 3000);

  ok(calls.global === 1, "el botón GENERAR GLOBAL llamó a /global exactamente una vez");
  ok(calls.control1 === 0 && calls.control3 === 0, "GENERAR GLOBAL no llamó a CONTROL 1 ni CONTROL 3");
  ok(bodies.global.length === 1 && "caja" in bodies.global[0], "el body de GENERAR GLOBAL manda 'caja' (usa el selector)");
  const texto = window.document.getElementById("mensual-resultado").textContent;
  ok(texto.indexOf("GLOBAL generado") !== -1, "el área de resultado muestra un mensaje claro (no JSON crudo)");
  ok(texto.indexOf("{") === -1, "el área de resultado NO muestra JSON técnico");
  ok(window.document.getElementById("mensual-resultado").className.indexOf("ok") !== -1, "el resultado se marca como 'ok'");
  dom.window.close();
}

async function test_boton_control1_preliminar_declina_cierre_no_llama_de_nuevo() {
  console.log("\n[12B] Botón CONTROL 1 (institucional): preliminar sin duplicados, el auditor DECLINA el cierre -> no hay segunda llamada");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.confirm = function () { return false; }; // el auditor declina el cierre contextual
  const { fn, calls, bodies } = _mockFetchMensual();
  window.fetch = fn;

  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-control1").click();
  await waitFor(() => window.document.getElementById("mensual-resultado").className.indexOf("ok") !== -1
    || window.document.getElementById("mensual-resultado").className.indexOf("error") !== -1, 3000);

  ok(calls.control1 === 1, "sin confirmar el cierre, /control1 se llamó UNA sola vez (la preliminar)");
  ok(calls.global === 0 && calls.control3 === 0, "CONTROL 1 no llamó a GLOBAL ni a CONTROL 3");
  ok(bodies.control1.length === 1 && !("caja" in bodies.control1[0]), "el body de CONTROL 1 nunca manda 'caja' (institucional)");
  ok(!("confirmacion_cierre" in bodies.control1[0]) || bodies.control1[0].confirmacion_cierre === undefined, "la llamada preliminar no manda confirmacion_cierre");
  ok(window.document.getElementById("mensual-resultado").textContent.indexOf("vista previa") !== -1, "el mensaje deja claro que fue una vista previa (PRELIMINAR)");
  dom.window.close();
}

async function test_boton_control1_preliminar_confirma_cierre_llama_de_nuevo_con_confirmacion() {
  console.log("\n[12B] Botón CONTROL 1 (institucional): preliminar sin duplicados, el auditor CONFIRMA el cierre -> segunda llamada con confirmacion_cierre=true");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.confirm = function () { return true; }; // el auditor confirma el cierre contextual
  const { fn, calls, bodies } = _mockFetchMensual({
    control1: function (n) {
      const cuerpo = n === 1
        ? { resultado: "OK", estado: "OK_SIN_DUPLICADOS", modo: "preliminar", historico_actualizado: false }
        : { resultado: "OK", estado: "OK_SIN_DUPLICADOS", modo: "cierre", historico_actualizado: true, filas_incorporadas_historico: 3 };
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(cuerpo) });
    },
  });
  window.fetch = fn;

  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-control1").click();
  await waitFor(() => calls.control1 === 2, 3000);
  await waitFor(() => window.document.getElementById("mensual-resultado").textContent.indexOf("incorporadas al histórico") !== -1, 3000);

  ok(calls.control1 === 2, "CONTROL 1 llamó dos veces: preliminar + cierre confirmado");
  ok(bodies.control1.length === 2, "se registraron ambos bodies");
  ok(!("confirmacion_cierre" in bodies.control1[0]) || bodies.control1[0].confirmacion_cierre === undefined, "la primera llamada (preliminar) no manda confirmacion_cierre");
  ok(bodies.control1[1].confirmacion_cierre === true, "la segunda llamada (cierre) manda confirmacion_cierre=true explícito");
  ok(!("caja" in bodies.control1[1]), "la llamada de cierre tampoco manda 'caja'");
  ok(window.document.getElementById("mensual-resultado").textContent.indexOf("incorporadas al histórico") !== -1, "el mensaje final refleja el cierre aplicado");
  dom.window.close();
}

async function test_boton_control3_llama_una_vez_sin_caja() {
  console.log("\n[12B] Botón CONTROL 3 (institucional): preliminar declina cierre -> una sola llamada, sin selector de caja");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  window.confirm = function () { return false; };
  const { fn, calls, bodies } = _mockFetchMensual();
  window.fetch = fn;

  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-control3").click();
  await waitFor(() => window.document.getElementById("mensual-resultado").className.indexOf("ok") !== -1
    || window.document.getElementById("mensual-resultado").className.indexOf("error") !== -1, 3000);

  ok(calls.control3 === 1, "el botón CONTROL 3 llamó a /control3 exactamente una vez");
  ok(calls.global === 0 && calls.control1 === 0, "CONTROL 3 no llamó a GLOBAL ni a CONTROL 1");
  ok(bodies.control3.length === 1 && !("caja" in bodies.control3[0]), "el body de CONTROL 3 nunca manda 'caja' (institucional)");
  dom.window.close();
}

async function test_control1_muestra_alertas_de_duplicados_institucionales() {
  console.log("\n[12E.6] CONTROL 1 institucional: alertas TIQ/AME requieren revisión");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function () {};
  const { fn } = _mockFetchMensual({
    control1: Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
      resultado: "OK", estado: "REVISAR_DUPLICADOS_ENCONTRADOS",
      alertas: [{ asignacion: "X", caja: "tiquipaya", archivo_origen: "SAP_GLOBAL_TIQ_SEPTIEMBRE_2026.xlsx", fila_origen: 16 }],
    }) }),
  });
  window.fetch = fn;
  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-control1").click();
  await waitFor(() => window.document.getElementById("mensual-resultado").className.indexOf("error") !== -1, 3000);
  ok(window.document.getElementById("mensual-resultado").textContent.indexOf("1 alerta") !== -1, "muestra la cantidad de alertas institucionales");
  dom.window.close();
}

async function test_global_bloqueado_post_cierre_muestra_mensaje_funcional() {
  console.log("\n[12E.6] GENERAR GLOBAL bloqueado tras el cierre: mensaje funcional, sin error Python crudo");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function () {};
  window.fetch = function (url) {
    if (url.indexOf("/global") !== -1) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "ERROR", codigo: "RuntimeError", mensaje: "PERIODO_CERRADO_CONTROL1: la Auditoría de Asignaciones de 2026-09 ya fue cerrada definitivamente; ..." }) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "ERROR", publication_mode: "official" }) });
  };
  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-global").click();
  await waitFor(() => window.document.getElementById("mensual-resultado").className.indexOf("error") !== -1, 3000);
  ok(window.document.getElementById("mensual-resultado").textContent === "El periodo ya fue cerrado por Auditoría de Asignaciones. El GLOBAL no puede regenerarse.", "mensaje funcional de GLOBAL bloqueado");
  dom.window.close();
}


// HOTFIX 2026-09-19 — en modo OFICIAL "Publicado" solo con la confirmación real de 06B/Drive.
async function _flujoOficial(cierreDatos, respuestaPublicar) {
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  const alertas = [];
  window.alert = function (msg) { alertas.push(msg); };
  window.confirm = function () { return true; };
  let publicarCalls = 0;
  window.fetch = function (url) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-of", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION", publication_mode: "official" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", cierres: [Object.assign({ fecha: "2026-09-11", archivo_esperado: "CIERRE 11-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR", requiere_revision: false, publicado: false, mensajes: [] }, cierreDatos)] }) });
    if (url.indexOf("/publicar") !== -1) {
      publicarCalls++;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", omitidos: [], publicados: [Object.assign({ fecha: "2026-09-11", archivo_esperado: "CIERRE 11-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR", requiere_revision: false, sha256: "abc123", mensajes: [] }, respuestaPublicar)] }) });
    }
    return Promise.reject(new Error("URL no esperada: " + url));
  };
  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelector("#tabla-body tr[data-hash]"), 5000);
  return { window, dom, alertas, publicarCalls: () => publicarCalls };
}

async function test_oficial_residuo_local_ya_publicado_no_muestra_publicado_y_permite_publicar() {
  console.log("\n[Hotfix] OFICIAL: YA_PUBLICADO local (residuo DEV, caso 11/09) NO es 'Publicado' y el botón sigue disponible");
  const f = await _flujoOficial({ estado_publicacion: "YA_PUBLICADO", publicado: false, sha256: "abc123", ruta_marker: "/dev/publicacion/markers/PROCESADO_abc123.json" }, {});
  ok(f.window.document.querySelector(".badge-publicado") === null, "la fila NO muestra el badge 'Publicado' por un YA_PUBLICADO local");
  ok(!!f.window.document.querySelector("#tabla-body tr[data-hash] button.publicar"), "el cierre sigue ofreciendo PUBLICAR");
  f.dom.window.close();
}
async function test_oficial_artefactos_locales_no_son_publicacion() {
  console.log("\n[Hotfix] OFICIAL: PUBLICADO/PUBLICACION_LOCAL_PREPARADA con SAP, resultado y marcador locales NO es 'Publicado'");
  for (const est of ["PUBLICADO", "PUBLICACION_LOCAL_PREPARADA"]) {
    const f = await _flujoOficial({ estado_publicacion: est, publicado: est === "PUBLICADO", ruta_sap_publicado: "/dev/publicacion/sap/SAP_11-09-2026.xlsx", ruta_resultado_publicado: "/dev/r.json", ruta_marker: "/dev/m.json" }, {});
    ok(f.window.document.querySelector(".badge-publicado") === null, est + ": sin badge 'Publicado'");
    ok(!!f.window.document.querySelector("#tabla-body tr[data-hash] button.publicar"), est + ": el botón PUBLICAR sigue disponible");
    f.dom.window.close();
  }
}
async function test_oficial_publicado_solo_con_publicado_oficial() {
  console.log("\n[Hotfix] OFICIAL: tras publicar, 'Publicado' SOLO con PUBLICADO_OFICIAL + publicado=true");
  const f = await _flujoOficial({}, { estado_publicacion: "PUBLICADO_OFICIAL", publicado: true, mensaje: "Cierre publicado oficialmente en Drive." });
  f.window.document.querySelector("#tabla-body tr[data-hash] button.publicar").click();
  await waitFor(() => f.publicarCalls() === 1 && f.window.document.querySelector(".badge-publicado"), 3000);
  ok(!!f.window.document.querySelector(".badge-publicado"), "PUBLICADO_OFICIAL con publicado=true muestra 'Publicado'");
  ok(f.window.document.querySelector("#tabla-body button.publicar") === null, "ya no se ofrece publicar");
  ok(f.alertas.length === 0, "sin alertas de error");
  f.dom.window.close();
}
async function test_oficial_error_publicacion_oficial_no_publicado_y_avisa() {
  console.log("\n[Hotfix] OFICIAL: ERROR_PUBLICACION_OFICIAL (06B ausente/fallido) NO muestra 'Publicado', avisa y permite reintentar");
  const msg = "La publicación oficial no se completó: no hay confirmación de Drive (06B) para este cierre.";
  const f = await _flujoOficial({}, { estado_publicacion: "ERROR_PUBLICACION_OFICIAL", publicado: false, mensaje: msg });
  f.window.document.querySelector("#tabla-body tr[data-hash] button.publicar").click();
  await waitFor(() => f.publicarCalls() === 1 && f.alertas.length > 0, 3000);
  await new Promise((r) => setTimeout(r, 100));
  ok(f.window.document.querySelector(".badge-publicado") === null, "NO aparece el badge 'Publicado'");
  ok(!!f.window.document.querySelector("#tabla-body tr[data-hash] button.publicar"), "el botón PUBLICAR sigue disponible para reintentar");
  ok(f.alertas[0].indexOf("NO se completó") !== -1 && f.alertas[0].indexOf("no hay confirmación de Drive") !== -1, "se avisa con un mensaje funcional");
  f.dom.window.close();
}
async function test_oficial_ya_publicado_oficial_es_idempotente() {
  console.log("\n[Hotfix] OFICIAL: YA_PUBLICADO_OFICIAL (marcador en Drive) se muestra como ya publicado");
  const f = await _flujoOficial({ estado_publicacion: "YA_PUBLICADO_OFICIAL", publicado: false }, {});
  ok(!!f.window.document.querySelector(".badge-publicado"), "muestra 'Publicado'");
  ok(f.window.document.querySelector("#tabla-body tr[data-hash] button.publicar") === null, "no ofrece publicar de nuevo");
  f.dom.window.close();
}

async function test_mensual_error_se_muestra_claramente() {
  console.log("\n[12B] Error en GLOBAL/CONTROL se muestra claro en el área de resultado");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const { fn, calls } = _mockFetchMensual({
    global: Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ resultado: "ERROR", mensaje: "SIN_SAP_PARA_CONSOLIDAR" }) }),
  });
  window.fetch = fn;

  await waitFor(() => window.document.getElementById("in-mensual-anio") && window.document.getElementById("in-mensual-anio").value !== "");
  window.document.getElementById("btn-mensual-global").click();
  await waitFor(() => calls.global === 1, 3000);
  await waitFor(() => window.document.getElementById("mensual-resultado").className.indexOf("error") !== -1, 3000);

  const el = window.document.getElementById("mensual-resultado");
  ok(el.className.indexOf("error") !== -1, "el resultado se marca como 'error'");
  ok(el.textContent.indexOf("SIN_SAP_PARA_CONSOLIDAR") !== -1, "el mensaje de error del backend es visible");
  ok(window.__lastAlert === undefined, "el error NO interrumpe con un alert() -- queda en el área de resultado");
  dom.window.close();
}

async function test_flujo_diario_nunca_llama_endpoints_mensuales() {
  console.log("\n[12B] El flujo diario (Procesar/Publicar) nunca dispara GLOBAL/CONTROL 1/CONTROL 3");
  const dom = makeDom("http://localhost/v3_control_cierres.html");
  const { window } = dom;
  window.alert = function (msg) { window.__lastAlert = msg; };
  const { fn, calls } = _mockFetchMensual();
  window.confirm = function () { return true; };
  let publicarCalls = 0;
  window.fetch = function (url, opts) {
    if (url.indexOf("/procesar") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", lote_id: "lote-12b", estado_lote: "PROCESANDO" }) });
    if (url.indexOf("/estado") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", estado_lote: "LISTO_PARA_REVISION_O_PUBLICACION", publication_mode: "official" }) });
    if (url.indexOf("/datos") !== -1) return Promise.resolve({
      ok: true, json: () => Promise.resolve({
        resultado: "OK", cierres: [{ fecha: "2026-09-10", archivo_esperado: "CIERRE 10-09-2026.xlsm", estado_final: "LISTO_PARA_PUBLICAR", requiere_revision: false, publicado: false, mensajes: [] }],
      }),
    });
    if (url.indexOf("/publicar") !== -1) {
      publicarCalls++;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ resultado: "OK", publicados: [{ fecha: "2026-09-10", estado_publicacion: "PUBLICADO", publicado: true }], omitidos: [] }) });
    }
    return fn(url);
  };

  await waitFor(() => window.document.getElementById("in-fecha-desde") && window.document.getElementById("in-fecha-desde").value !== "");
  window.document.getElementById("btn-procesar").click();
  await waitFor(() => window.document.querySelectorAll("#tabla-body tr[data-hash] button.publicar").length === 1, 5000);
  window.document.querySelector("#tabla-body tr[data-hash] button.publicar").click();
  await waitFor(() => publicarCalls === 1, 3000);

  ok(calls.global === 0, "Procesar+Publicar nunca llamaron a /global");
  ok(calls.control1 === 0, "Procesar+Publicar nunca llamaron a /control1");
  ok(calls.control3 === 0, "Procesar+Publicar nunca llamaron a /control3");
  dom.window.close();
}

(async () => {
  await test_demo_no_llama_backend();
  await test_procesar_rango_valido();
  await test_selector_caja_opciones_y_default();
  await test_crear_lote_america_manda_caja_america();
  await test_acciones_posteriores_no_mandan_ni_cambian_caja();
  await test_sin_archivo();
  await test_revision_y_correccion();
  await test_campos_aplicables_por_excepcion();
  await test_post_correccion_reproceso_listo();
  await test_post_correccion_reproceso_con_nueva_excepcion();
  await test_post_correccion_reproceso_sin_excepciones();
  await test_publicacion();
  await test_cancelar_confirmacion_publicar_no_llama_backend();
  await test_cierre_ya_publicado_no_ofrece_boton_ni_infla_historial();
  await test_error_backend();
  await test_no_publicar_no_habilitado();
  await test_maestro_sin_cobertura_no_ofrece_correccion_ni_publicacion();
  await test_ajustes_interfaz_fase_10f();
  await test_publication_mode_dev_muestra_badge_dev();
  await test_publication_mode_official_muestra_badge_oficial();
  await test_publication_mode_demo_nunca_llama_backend();
  await test_boton_global_llama_una_vez_y_muestra_resultado();
  await test_boton_control1_preliminar_declina_cierre_no_llama_de_nuevo();
  await test_boton_control1_preliminar_confirma_cierre_llama_de_nuevo_con_confirmacion();
  await test_boton_control3_llama_una_vez_sin_caja();
  await test_control1_muestra_alertas_de_duplicados_institucionales();
  await test_mensual_error_se_muestra_claramente();
  await test_oficial_residuo_local_ya_publicado_no_muestra_publicado_y_permite_publicar();
  await test_oficial_artefactos_locales_no_son_publicacion();
  await test_oficial_publicado_solo_con_publicado_oficial();
  await test_oficial_error_publicacion_oficial_no_publicado_y_avisa();
  await test_oficial_ya_publicado_oficial_es_idempotente();
  await test_global_bloqueado_post_cierre_muestra_mensaje_funcional();
  await test_flujo_diario_nunca_llama_endpoints_mensuales();

  console.log("\n=========================================");
  console.log(passed + " passed, " + failures + " failed");
  console.log("=========================================");
  process.exit(failures > 0 ? 1 : 0);
})();

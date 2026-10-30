// Convierte un HTML local a PDF A4 con Chromium (Playwright ya instalado en el entorno).
// Uso: node render.js entrada.html salida.pdf
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const [, , entrada, salida] = process.argv;
  if (!entrada || !salida) {
    console.error('Uso: node render.js entrada.html salida.pdf');
    process.exit(1);
  }
  let navegador;
  try {
    navegador = await chromium.launch();
  } catch (e) {
    navegador = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  }
  const pagina = await navegador.newPage();
  await pagina.goto('file://' + path.resolve(entrada));
  await pagina.pdf({
    path: salida,
    format: 'A4',
    printBackground: true,
    margin: { top: '10mm', bottom: '10mm', left: '8mm', right: '8mm' },
  });
  await navegador.close();
  console.log('PDF generado:', salida);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});

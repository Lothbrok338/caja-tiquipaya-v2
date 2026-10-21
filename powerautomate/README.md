# Power Automate — paquetes ZIP generados

Generar: `python powerautomate/build_zip.py --version 0.1.0` → `powerautomate/dist/`.
Tests: `PYTHONPATH=. python3 -m unittest tests.test_powerautomate_zip`.
Cada cambio al flujo = subir `--version` y volver a importar (el build es determinístico).

**Estado de verificación: estructura validada por tests propios; NO importado aún en un tenant real.**
Si la importación falla, enviar el mensaje de error exacto y/o un ZIP exportado de referencia; se corrige el generador, no el flujo a mano.

## Prueba mínima (Flujo 00) — paso a paso

### A. Desplegar la API en Railway
1. Railway → New Project → Deploy from GitHub repo → `Lothbrok338/caja-tiquipaya-v2`, rama `claude/charming-pasteur-l1uxy1` (o `main` tras fusionar). **Crear un servicio nuevo; no tocar el existente.**
2. Service → Variables: `RAILWAY_DOCKERFILE_PATH=api_caja/Dockerfile`, `API_KEYS=<clave larga aleatoria>`, `CAJAS_HABILITADAS=AYACUCHO`.
3. Settings → Networking → Generate Domain. Probar `https://<dominio>/v1/health` → `{"status":"ok",...}`.

### B. Importar el ZIP (formato heredado)
1. make.powerautomate.com → **Mis flujos** → **Importar** → **Importar paquete (heredado)** → subir `Flujo00_Smoke_HTTP_v0.1.0_legacy.zip`.
2. En *Contenido del paquete*, el flujo aparece con acción **Crear como nuevo**; no pide conexiones. **Importar**.
3. Abrir el flujo → **Editar** → en *Parámetros* (o en la acción HTTP_ping) reemplazar `https://REEMPLAZAR.up.railway.app` por tu dominio de Railway → **Guardar**.
   - Formato solución: **Soluciones → Importar solución**, completar la variable de entorno *API Base URL (Railway)*.

### C. Probar
1. **Probar → Manualmente → Probar**; Caja = `AYACUCHO`, API key = la de `API_KEYS`.
2. Resultado esperado: ejecución verde; `Resultado_OK` = `OK | caja=AYACUCHO | engine=... | corr=<guid>`.
3. Prueba negativa: API key incorrecta → HTTP_ping falla con 401 (esperado).

Conexiones y parámetros de este flujo: **ninguna conexión**; 1 parámetro (`ApiBaseUrl`) y 2 entradas al ejecutar (Caja, API key). La API key nunca va en el ZIP.

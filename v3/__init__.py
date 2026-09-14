"""Paquete v3 — módulos Python reales de Caja Tiquipaya V3.

FASE 5 (implementación funcional progresiva): módulo por módulo, en el
orden obligatorio 01 INGESTA -> 02 MATERIALIZACION -> ... -> 07 AUDITORIA.
Cada módulo aquí es NUEVO e independiente de V2 (ningún archivo de la raíz
del repo — motor_tiquipaya.py, excel_io.py, sap_writer.py,
pipeline_tiquipaya.py, run_batch.py, correcciones_tiquipaya.py,
consolidador_mensual.py, control_asignaciones.py, control_cxc_cxp.py,
aplicar_correccion.py, publicar_cierre.py — se modifica jamás desde este
paquete). Donde V2 ya resuelve algo con una función determinística y
testeada, este paquete la REUTILIZA por import en vez de reimplementarla
(ver v3/ingesta.py: reutiliza run_batch.generar_rango_fechas y
run_batch.nombre_cierre_esperado tal cual).
"""

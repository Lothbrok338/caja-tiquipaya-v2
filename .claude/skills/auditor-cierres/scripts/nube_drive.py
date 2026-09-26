"""nube_drive.py — Materializacion TEMPORAL y segura de archivos de Google Drive (flujo cloud end-to-end).

Claude obtiene los binarios con la herramienta `download_file_content` del conector de Drive. Cuando el
resultado es grande, el harness NO lo devuelve en el chat: lo guarda en disco como un JSON
`{content(base64), id, mimeType, title}` y avisa la ruta ("Output has been saved to ..."). Este script
decodifica ESE archivo con Python (nunca se reescribe base64 a mano), valida el binario y lo deja en una
carpeta temporal de sesion, junto con un manifiesto. Al terminar, `limpiar` borra todo.

Comandos (stdout: un JSON compacto):
  iniciar   [--base DIR]                      crea la carpeta temporal de sesion y el manifiesto
  registrar --sesion S --rol cierre|macros --drive-id ID --nombre N --tam-drive BYTES --json-fuente F
            [--caja tiquipaya|america] [--modificado ISO] [--conservar-fuente]
  anotar    --sesion S --clave K --valor V    deja constancia (p.ej. archivos ignorados de ENTRADA)
  estado    --sesion S                        resume el manifiesto
  limpiar   --sesion S                        borra la carpeta de sesion (solo si es una sesion propia)

Garantias de `registrar`: id y titulo del JSON == los pedidos; tamano decodificado == tamano en Drive
(`fileSize` del listado); ZIP integro; estructura de libro (workbook.xml) y, si existe, vbaProject.bin
presente; sha256 registrado; no se sobrescribe nada. Tras registrar, el JSON fuente (que contiene una copia
en base64 del archivo) se borra si es un resultado del conector (carpeta `tool-results`, nombre `mcp-*`).
Nunca escribe en Drive ni toca originales.
"""
import argparse
import base64
import binascii
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

MARCA = ".auditor_cierres_sesion"
PREFIJO_SESION = "auditor_cierres_"
CAJAS = ("tiquipaya", "america")
RE_CIERRE = re.compile(r"^CIERRE (\d{2})-(\d{2})-(\d{4})\.xlsm$")
RE_MACROS = re.compile(r"^MACROS ([A-ZÁÉÍÓÚÑ]+)\.xlsm$")
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
         "NOVIEMBRE", "DICIEMBRE"]


class ErrorNube(Exception):
    pass


def _salida(obj, codigo=0):
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    return codigo


def _ruta_manifiesto(sesion):
    return os.path.join(sesion, "manifiesto.json")


def _validar_sesion(sesion):
    sesion = os.path.abspath(sesion)
    if not os.path.basename(sesion).startswith(PREFIJO_SESION) or not os.path.isfile(os.path.join(sesion, MARCA)):
        raise ErrorNube("SESION_INVALIDA: %s no es una carpeta de sesion de auditor-cierres" % sesion)
    return sesion


def _leer_manifiesto(sesion):
    with open(_ruta_manifiesto(sesion), encoding="utf-8") as f:
        return json.load(f)


def _guardar_manifiesto(sesion, m):
    tmp = _ruta_manifiesto(sesion) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ruta_manifiesto(sesion))


def iniciar(base=None):
    base = base or tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    sesion = tempfile.mkdtemp(prefix=PREFIJO_SESION, dir=base)
    with open(os.path.join(sesion, MARCA), "w", encoding="utf-8") as f:
        f.write("carpeta temporal de auditor-cierres; se borra con `nube_drive.py limpiar`\n")
    _guardar_manifiesto(sesion, {"version": 1, "creada": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "cierres": [], "macros": [], "notas": {}})
    return {"sesion": sesion}


def _es_fuente_del_conector(ruta):
    ruta = os.path.abspath(ruta)
    return os.path.basename(os.path.dirname(ruta)) == "tool-results" and os.path.basename(ruta).startswith("mcp-")


def registrar(sesion, rol, drive_id, nombre, tam_drive, json_fuente, caja=None, modificado=None, conservar_fuente=False):
    sesion = _validar_sesion(sesion)
    if rol == "cierre":
        if caja not in CAJAS:
            raise ErrorNube("CAJA_REQUERIDA: --caja debe ser tiquipaya o america")
        if not RE_CIERRE.match(nombre):
            raise ErrorNube("NOMBRE_CIERRE_INVALIDO: %r no es 'CIERRE DD-MM-YYYY.xlsm'" % nombre)
        destino_dir = os.path.join(sesion, caja.upper())
    elif rol == "macros":
        if not RE_MACROS.match(nombre):
            raise ErrorNube("NOMBRE_MACROS_INVALIDO: %r no es 'MACROS <MES>.xlsm'" % nombre)
        destino_dir = os.path.join(sesion, "MACROS")
    else:
        raise ErrorNube("ROL_INVALIDO: %r" % rol)

    with open(json_fuente, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict) or "content" not in d:
        raise ErrorNube("FUENTE_SIN_CONTENIDO: el JSON no trae 'content' (el archivo no se guardo en disco)")
    if d.get("id") != drive_id:
        raise ErrorNube("ID_NO_COINCIDE: pedido %s, recibido %s" % (drive_id, d.get("id")))
    if d.get("title") != nombre:
        raise ErrorNube("TITULO_NO_COINCIDE: pedido %r, recibido %r" % (nombre, d.get("title")))
    try:
        datos = base64.b64decode(d["content"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErrorNube("BASE64_INVALIDO: %s" % exc)
    if len(datos) != int(tam_drive):
        raise ErrorNube("TAMANO_NO_COINCIDE: Drive %s bytes, decodificado %d" % (tam_drive, len(datos)))

    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, nombre)
    if os.path.exists(destino):
        raise ErrorNube("DUPLICADO: %s ya fue materializado en esta sesion" % nombre)
    try:
        with open(destino, "wb") as f:
            f.write(datos)
        with zipfile.ZipFile(destino) as z:
            if z.testzip() is not None:
                raise ErrorNube("ZIP_CORRUPTO: %s" % nombre)
            nombres = set(z.namelist())
        if "xl/workbook.xml" not in nombres or "[Content_Types].xml" not in nombres:
            raise ErrorNube("NO_ES_LIBRO_EXCEL: %s" % nombre)
    except (zipfile.BadZipFile, ErrorNube):
        if os.path.exists(destino):
            os.remove(destino)
        raise
    item = {"nombre": nombre, "drive_id": drive_id, "ruta": destino, "bytes": len(datos),
            "sha256": hashlib.sha256(datos).hexdigest(), "vba": "xl/vbaProject.bin" in nombres,
            "modificado_drive": modificado}
    m = _leer_manifiesto(sesion)
    if rol == "cierre":
        item["caja"] = caja
        mm = RE_CIERRE.match(nombre)
        item["fecha"] = "%s-%s-%s" % (mm.group(3), mm.group(2), mm.group(1))
        m["cierres"].append(item)
    else:
        item["periodo_mes"] = RE_MACROS.match(nombre).group(1)
        m["macros"].append(item)
    _guardar_manifiesto(sesion, m)

    fuente_borrada = False
    if not conservar_fuente and _es_fuente_del_conector(json_fuente):
        os.remove(json_fuente)
        fuente_borrada = True
    return {"ok": True, "rol": rol, "caja": caja, "nombre": nombre, "bytes": item["bytes"], "sha256": item["sha256"][:12],
            "vba": item["vba"], "fuente_borrada": fuente_borrada}


def anotar(sesion, clave, valor):
    sesion = _validar_sesion(sesion)
    m = _leer_manifiesto(sesion)
    try:
        valor = json.loads(valor)
    except ValueError:
        pass
    m["notas"][clave] = valor
    _guardar_manifiesto(sesion, m)
    return {"ok": True, "clave": clave}


def estado(sesion):
    sesion = _validar_sesion(sesion)
    m = _leer_manifiesto(sesion)
    por_caja = {}
    for c in m["cierres"]:
        por_caja[c["caja"]] = por_caja.get(c["caja"], 0) + 1
    return {"sesion": sesion, "cierres": por_caja, "macros": [x["nombre"] for x in m["macros"]],
            "notas": sorted(m["notas"])}


def limpiar(sesion):
    sesion = _validar_sesion(sesion)
    n = sum(len(fs) for _, _, fs in os.walk(sesion))
    b = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(sesion) for f in fs)
    shutil.rmtree(sesion)
    return {"ok": not os.path.exists(sesion), "archivos_borrados": n, "bytes_borrados": b}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Materializacion temporal de Drive para auditor-cierres")
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("iniciar")
    a.add_argument("--base")
    a = sp.add_parser("registrar")
    a.add_argument("--sesion", required=True)
    a.add_argument("--rol", required=True, choices=("cierre", "macros"))
    a.add_argument("--caja", choices=CAJAS)
    a.add_argument("--drive-id", required=True)
    a.add_argument("--nombre", required=True)
    a.add_argument("--tam-drive", required=True, type=int)
    a.add_argument("--json-fuente", required=True)
    a.add_argument("--modificado")
    a.add_argument("--conservar-fuente", action="store_true")
    a = sp.add_parser("anotar")
    a.add_argument("--sesion", required=True)
    a.add_argument("--clave", required=True)
    a.add_argument("--valor", required=True)
    for c in ("estado", "limpiar"):
        a = sp.add_parser(c)
        a.add_argument("--sesion", required=True)
    ns = p.parse_args(argv)
    try:
        if ns.cmd == "iniciar":
            return _salida(iniciar(ns.base))
        if ns.cmd == "registrar":
            return _salida(registrar(ns.sesion, ns.rol, ns.drive_id, ns.nombre, ns.tam_drive, ns.json_fuente, ns.caja,
                                     ns.modificado, ns.conservar_fuente))
        if ns.cmd == "anotar":
            return _salida(anotar(ns.sesion, ns.clave, ns.valor))
        if ns.cmd == "estado":
            return _salida(estado(ns.sesion))
        return _salida(limpiar(ns.sesion))
    except (ErrorNube, OSError, ValueError) as exc:
        return _salida({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}, 1)


if __name__ == "__main__":
    sys.exit(main())

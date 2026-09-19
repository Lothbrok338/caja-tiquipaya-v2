"""v3/shadow_guard.py — guarda de entorno SHADOW/DEV (migración Railway, 2026-09).

Bloquea la publicación oficial en Drive de forma incondicional cuando el
proceso corre con `TIQ_BLOCK_OFFICIAL_PUBLISH=true`. Vive en Python
porque Python es la única autoridad de reglas de este sistema: ningún
flag de request (`modo_oficial`, `publication_mode`) ni clic en la
interfaz puede saltarse esta guarda, sin importar qué decida n8n o el
navegador. No modifica ninguna regla contable — solo el gate de
publicación oficial (CONTRACT-011 ya separaba procesar de publicar; esto
añade un segundo cierre, de entorno, encima de ese contrato).

IMPORTANTE — la variable es opt-in, no fail-safe: por defecto (sin la
variable, o con cualquier valor que no sea exactamente "true"/"1"/"yes")
esta guarda está INACTIVA y el comportamiento es idéntico al de antes de
esta migración. Así el Codespace/entorno productivo real, que nunca fija
esta variable, no cambia de comportamiento. SOLO el servicio Railway
`cajas-gabo-shadow` la fija explícitamente a `true` en sus variables de
entorno — ver DEPLOY_RAILWAY.md.
"""
import os


class PublicacionOficialBloqueadaError(RuntimeError):
    """Se intentó una publicación oficial con TIQ_BLOCK_OFFICIAL_PUBLISH=true."""


def bloqueo_publicacion_oficial_activo():
    valor = os.environ.get("TIQ_BLOCK_OFFICIAL_PUBLISH", "").strip().lower()
    return valor in ("true", "1", "yes")


def exigir_no_bloqueo_para_publicacion_oficial():
    if bloqueo_publicacion_oficial_activo():
        raise PublicacionOficialBloqueadaError(
            "PUBLICACION_OFICIAL_BLOQUEADA_POR_ENTORNO: este proceso corre con "
            "TIQ_BLOCK_OFFICIAL_PUBLISH=true (entorno sombra/dev, p. ej. Railway "
            "cajas-gabo-shadow). La publicación oficial en Drive está deshabilitada "
            "incondicionalmente, sin importar modo_oficial o publication_mode "
            "recibidos. Esto no es una regla contable: es una guarda de entorno que "
            "solo aplica donde se fija explícitamente esta variable."
        )

"""api_caja/main.py — API REST estable para Power Automate (Fase 0: smoke test).

Fase 0 NO ejecuta lógica contable: solo prueba conectividad, autenticación y
trazabilidad (X-Correlation-Id) entre Power Automate (HTTP Premium) y Railway.

Variables de entorno:
  API_KEYS        claves válidas separadas por coma (permite rotación). Si no
                  está definida, TODA ruta protegida responde 503 (falla cerrada).
  CAJAS_HABILITADAS  cajas aceptadas, separadas por coma (default: AYACUCHO).
  ENGINE_VERSION  versión/commit del motor; si falta se usa RAILWAY_GIT_COMMIT_SHA.
"""

import hmac
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

API_VERSION = "v1"
_RE_CORRELATION = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

app = FastAPI(title="CAJAS GABO API", version="0.1.0", docs_url=None, redoc_url=None)


def _cajas_habilitadas():
    raw = os.environ.get("CAJAS_HABILITADAS", "AYACUCHO")
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def _engine_version():
    return os.environ.get("ENGINE_VERSION") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "desconocida"


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def correlation_id(x_correlation_id: str | None = Header(default=None)):
    """Usa el X-Correlation-Id del llamador si es válido; si no, genera uno."""
    if x_correlation_id and _RE_CORRELATION.match(x_correlation_id):
        return x_correlation_id
    return str(uuid.uuid4())


def autenticar(x_api_key: str | None = Header(default=None)):
    claves = [c.strip() for c in os.environ.get("API_KEYS", "").split(",") if c.strip()]
    if not claves:
        raise HTTPException(status_code=503, detail="API_KEYS_NO_CONFIGURADAS")
    if not x_api_key or not any(hmac.compare_digest(x_api_key, c) for c in claves):
        raise HTTPException(status_code=401, detail="API_KEY_INVALIDA")


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    cid = request.headers.get("x-correlation-id") or "n/a"
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "codigo": exc.detail, "correlation_id": cid},
        headers={"X-Correlation-Id": cid},
    )


class PingIn(BaseModel):
    caja: str = Field(min_length=1, max_length=40)


@app.get(f"/{API_VERSION}/health")
def health():
    return {"status": "ok", "api": API_VERSION, "engine_version": _engine_version()}


@app.post(f"/{API_VERSION}/ping", dependencies=[Depends(autenticar)])
def ping(body: PingIn, cid: str = Depends(correlation_id)):
    caja = body.caja.strip().upper()
    if caja not in _cajas_habilitadas():
        raise HTTPException(status_code=422, detail="CAJA_NO_HABILITADA")
    return JSONResponse(
        content={
            "status": "ok",
            "caja": caja,
            "correlation_id": cid,
            "api": API_VERSION,
            "engine_version": _engine_version(),
            "timestamp_utc": _ahora(),
        },
        headers={"X-Correlation-Id": cid},
    )

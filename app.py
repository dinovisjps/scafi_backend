"""
app.py — FastAPI app, middleware (request-id/IP), routes, lifecycle
"""
from __future__ import annotations

import time, uuid, logging, json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import setup_logging, request_id_var, client_ip_var, init_db_pool, close_db_pool, is_ready
from dtos import AnagrafichePayload, InvoiceResponse, ServiceResponse
import service as services

setup_logging()
app = FastAPI(title="Scafi Backend Integration", version="1.0.0")
logger = logging.getLogger(__name__)

# -------- Per-request context + access log + global error catcher
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_var.set(rid)
    client_ip = request.headers.get("x-forwarded-for","").split(",")[0].strip() or request.client.host
    client_ip_var.set(client_ip)

    start = time.perf_counter()
    logger.info(">> %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error")
        return JSONResponse(status_code=500, content={"success":"0","message":"Internal Server Error"})
    finally:
        ms = (time.perf_counter() - start) * 1000.0
        logger.info("<< %s %s %s %.1fms", request.method, request.url.path, getattr(response, "status_code", "?"), ms)

    response.headers["X-Request-ID"] = rid
    return response

# -------- Lifecycle hooks
@app.on_event("startup")
def on_startup():
    logger.info("App starting up"); init_db_pool(); logger.info("Startup complete")

@app.on_event("shutdown")
def on_shutdown():
    logger.info("App shutting down"); close_db_pool(); logger.info("Shutdown complete")

# -------- Endpoints (sync handlers run in FastAPI's threadpool)
@app.post("/integration/anagrafiche", response_model=ServiceResponse)
def create_anagrafiche(p: AnagrafichePayload):
    payload = p.model_dump() if hasattr(p, "model_dump") else p.dict()
    logger.debug("Endpoint /integration/anagrafiche invoked with payload: %s", json.dumps(payload, default=str))
    return services.create_anagrafiche(p)

@app.post("/integration/fatture", response_model=ServiceResponse)
def create_fatture(p: InvoiceResponse):
    payload = p.model_dump() if hasattr(p, "model_dump") else p.dict()
    logger.debug("Endpoint /integration/fatture invoked with payload: %s", json.dumps(payload, default=str))
    return services.create_fatture(p)

# -------- Diagnostics
@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/readyz")
def readyz():
    return {"ready": is_ready()}

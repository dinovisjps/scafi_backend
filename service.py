"""
services.py — Business logic: DB upserts + calls to JDE
"""
from __future__ import annotations
import logging
from typing import Dict, Any

from dtos import AnagrafichePayload, InvoiceResponse, ServiceResponse
from core import (
    get_db_conn, put_db_conn,
    http_json, JDE_BASE_URL, JDE_PATH_ANAG, JDE_PATH_FATT,
    JDE_CREDENTIALS_JSON, DRY_RUN_DB
)

logger = logging.getLogger(__name__)

def _attach_credentials(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Optionally inject credentials (from env JDE_CREDENTIALS_JSON) into the outbound payload
    to keep parity with legacy flows that added them inside the JSON body.
    """
    if JDE_CREDENTIALS_JSON and "credentials" not in payload:
        try:
            import json as _json
            payload = dict(payload)
            payload["credentials"] = _json.loads(JDE_CREDENTIALS_JSON)
        except Exception as e:
            logger.warning("Invalid JDE_CREDENTIALS_JSON: %s", e)
    return payload

# ----------------- DB helpers (insert your real SQL where marked)
def _db_upsert_anagrafica(p: AnagrafichePayload) -> None:
    if DRY_RUN_DB:
        logger.info("DRY_RUN_DB: skipping DB upsert anagrafica %s", p.codice)
        return
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                logger.debug("DB upsert anagrafica codice=%s", p.codice)
                # TODO: REPLACE WITH REAL SQL:
                # Example:
                # cur.execute("SELECT my_upsert_anagrafica(%s, %s, ...)", (...))
                cur.execute("SELECT 1")
    finally:
        put_db_conn(conn)

def _db_upsert_fattura(p: InvoiceResponse) -> None:
    if DRY_RUN_DB:
        logger.info("DRY_RUN_DB: skipping DB upsert fattura %s", p.DocumentNumber)
        return
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                logger.debug("DB upsert fattura number=%s company=%s", p.DocumentNumber, p.DocumentCompany)
                # TODO: REPLACE WITH REAL SQL:
                # Example:
                # cur.execute("SELECT my_upsert_fattura(%s, %s, ...)", (...))
                cur.execute("SELECT 1")
    finally:
        put_db_conn(conn)

# ----------------- Public services
def create_anagrafiche(p: AnagrafichePayload) -> ServiceResponse:
    try:
        _db_upsert_anagrafica(p)
        payload = p.model_dump() if hasattr(p, "model_dump") else p.dict()
        payload = _attach_credentials(payload)
        status, _jde = http_json("POST", JDE_BASE_URL, JDE_PATH_ANAG, payload)
        if status >= 400:
            msg = f"JDE returned status {status}"
            logger.error(msg)
            return ServiceResponse(success="0", message=msg)
        return ServiceResponse(success="1", message="OK")
    except Exception as e:
        logger.exception("create_anagrafiche failed")
        return ServiceResponse(success="0", message=str(e))

def create_fatture(p: InvoiceResponse) -> ServiceResponse:
    try:
        _db_upsert_fattura(p)
        payload = p.model_dump() if hasattr(p, "model_dump") else p.dict()
        payload = _attach_credentials(payload)
        status, _jde = http_json("POST", JDE_BASE_URL, JDE_PATH_FATT, payload)
        if status >= 400:
            msg = f"JDE returned status {status}"
            logger.error(msg)
            return ServiceResponse(success="0", message=msg)
        return ServiceResponse(success="1", message="OK")
    except Exception as e:
        logger.exception("create_fatture failed")
        return ServiceResponse(success="0", message=str(e))

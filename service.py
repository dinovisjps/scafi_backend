"""
services.py — Business logic: DB upserts + calls to JDE
"""
from __future__ import annotations
import logging
from typing import Dict, Any, Optional
import json as _json
from base64 import b64encode

from dtos import AnagrafichePayload, InvoiceResponse, ServiceResponse
from core import (
    get_db_conn, put_db_conn,
    http_json, JDE_BASE_URL, JDE_PATH_ANAG, JDE_PATH_FATT,
    JDE_CREDENTIALS_JSON, DRY_RUN_DB, send_mail
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
                cur.execute("SELECT 1")
    finally:
        put_db_conn(conn)


def _basic_auth_header_for_company(company: str) -> Optional[str]:
    """Return a Basic auth header value for the given company if present in JDE_CREDENTIALS_JSON.
    Expected JSON format: [{"company":"XYZ","user":"u","password":"p"}, ...]
    """
    if not JDE_CREDENTIALS_JSON:
        return None
    try:
        creds = _json.loads(JDE_CREDENTIALS_JSON)
        if isinstance(creds, list):
            for c in creds:
                if c.get("company") == company:
                    user = c.get("user", "")
                    password = c.get("password", "")
                    token = b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
                    return f"Basic {token}"
    except Exception as e:
        logger.warning("Failed parsing JDE_CREDENTIALS_JSON: %s", e)
    return None


def _extract_jde_fields(jde_resp: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize likely field names from JDE responses into a consistent mapping."""
    def first(*keys: str) -> Any:
        for k in keys:
            if k in jde_resp:
                return jde_resp.get(k)
        return None

    return {
        "message": first("message", "jdeSimpleMessage", "userDefinedErrorText"),
        "jde_status": first("jde__status", "jdeStatus", "jde_status"),
        "jde_start_timestamp": first("jde__startTimestamp", "jdeStartTimestamp"),
        "jde_end_timestamp": first("jde__endTimestamp", "jdeEndTimestamp"),
        "status": first("status"),
        "batchno": first("BatchNo", "batchNo", "batchno"),
        "jde_server_execution_seconds": first("jde__serverExecutionSeconds", "jdeServerExecutionSeconds"),
        "jde_log_id": first("jdeLogId", "jde_log_id", "exceptionId"),
    }


def _db_insert_integration_log(
    *,
    object_id: Any,
    object_type: str,
    message: str,
    jde_status: Optional[str],
    jde_start_timestamp: Optional[str],
    jde_end_timestamp: Optional[str],
    status: Optional[str],
    batchno: Optional[str],
    jde_server_execution_seconds: Optional[Any],
    jde_log_id: Optional[str],
    integration_type: str,
    code: Any,
    company: str,
) -> None:
    if DRY_RUN_DB:
        logger.info("DRY_RUN_DB: skipping insert into integration_log (object_id=%s)", object_id)
        return
    sql = (
        "insert into integration_log (object_id, object_type, message, jde_status, jde_start_timestamp, jde_end_timestamp, "
        "status, batchno, jde_server_execution_seconds, jde_log_id, integration_type, code, Company) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    [
                        object_id,
                        object_type,
                        message,
                        jde_status,
                        jde_start_timestamp,
                        jde_end_timestamp,
                        status,
                        batchno,
                        jde_server_execution_seconds,
                        jde_log_id or "0",
                        integration_type,
                        code,
                        company,
                    ],
                )
    finally:
        put_db_conn(conn)


def _db_update_integration_log_message_by_jde_log_id(jde_log_id: Any, message: str) -> None:
    if DRY_RUN_DB:
        logger.info("DRY_RUN_DB: skipping update integration_log for jde_log_id=%s", jde_log_id)
        return
    sql = "UPDATE integration_log SET message = %s WHERE jde_log_id = %s"
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, [message, str(jde_log_id)])
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
    """
    Create invoices in JDE:
    - Build payload from request
    - Use per-company Basic Auth from JDE_CREDENTIALS_JSON to call orchestrator
    - If JDE reports ERROR, retrieve detailed error log and email a notification
    """
    try:
        #_db_upsert_fattura(p)

        payload: Dict[str, Any] = p.model_dump() if hasattr(p, "model_dump") else p.dict()

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        auth_header = _basic_auth_header_for_company(p.Company)
        if auth_header:
            headers["Authorization"] = auth_header

        status, jde_resp = http_json("POST", JDE_BASE_URL, JDE_PATH_FATT, payload, headers=headers)
        if status >= 400:
            msg = f"JDE returned HTTP {status} on invoice insert."
            logger.error(msg)
            # Insert an integration log row even for HTTP errors (with minimal fields)
            try:
                fields = _extract_jde_fields(jde_resp if isinstance(jde_resp, dict) else {})
                default_msg = msg
                logger.debug(fields.get("message"))
                _db_insert_integration_log(
                    object_id=p.CustomId,
                    object_type=p.DocumentType,
                    message=fields.get("messagea") or default_msg,
                    jde_status=fields.get("jde_status"),
                    jde_start_timestamp=fields.get("jde_start_timestamp"),
                    jde_end_timestamp=fields.get("jde_end_timestamp"),
                    status=fields.get("status"),
                    batchno=fields.get("batchno"),
                    jde_server_execution_seconds=fields.get("jde_server_execution_seconds"),
                    jde_log_id=fields.get("jde_log_id"),
                    integration_type="INV",
                    code=p.DocumentNumber,
                    company=p.DocumentCompany,
                )
            except Exception as log_err:
                logger.warning("Failed to insert integration_log for HTTP error: %s", log_err)
            return ServiceResponse(success="0", message=f"{default_msg}\n{fields.get('message') or default_msg}")

        # Insert integration log for the response
        try:
            fields = _extract_jde_fields(jde_resp if isinstance(jde_resp, dict) else {})
            default_msg = fields.get("message") or (
                f"Invoice no. {p.DocumentNumber} {p.DocumentType} {p.DocumentCompany} successfully inserted"
            )
            _db_insert_integration_log(
                object_id=p.CustomId,
                object_type=p.DocumentType,
                message=default_msg,
                jde_status=fields.get("jde_status"),
                jde_start_timestamp=fields.get("jde_start_timestamp"),
                jde_end_timestamp=fields.get("jde_end_timestamp"),
                status=fields.get("status"),
                batchno=fields.get("batchno"),
                jde_server_execution_seconds=fields.get("jde_server_execution_seconds"),
                jde_log_id=fields.get("jde_log_id"),
                integration_type="INV",
                code=p.DocumentNumber,
                company=p.DocumentCompany,
            )
        except Exception as log_err:
            logger.warning("Failed to insert integration_log: %s", log_err)

        # If JDE responded with logical ERROR, fetch detailed error log and update DB row
        #TODO: jde_log_id is not always present as numeric jdeLogId > Unique Key ID (Internal)-UKID
        if str(jde_resp.get("status", "")).upper() == "ERROR":
            jde_log_id = fields.get("jde_log_id")
            error_log_path = "/jderest/orchestrator/ALFA_ORC_RetriveErrorLog"
            err_payload = {"jdeLogId": jde_log_id} if jde_log_id is not None else {}
            try:
                _status2, err_resp = http_json("POST", JDE_BASE_URL, error_log_path, err_payload, headers=headers)
                error_text = err_resp.get("ErrorLog") or _json.dumps(err_resp)
            except Exception as e:
                error_text = f"Failed to retrieve JDE error log: {e}"

            try:
                if jde_log_id is not None:
                    _db_update_integration_log_message_by_jde_log_id(jde_log_id, error_text)
            except Exception as upd_err:
                logger.warning("Failed to update integration_log message: %s", upd_err)

            subject = f"JDE error for invoice id {p.CustomId} type {p.DocumentType} logId {jde_log_id}"
            body = (
                f"An error occurred while inserting invoice.\n"
                f"CustomId: {p.CustomId}\n"
                f"DocumentType: {p.DocumentType}\n"
                f"Company: {p.Company}\n"
                f"DocumentNumber: {p.DocumentNumber}\n"
                f"JDE Log ID: {jde_log_id}\n\n"
                f"Details: {error_text}\n"
            )
            try:
                send_mail(subject, body)
            except Exception as e:
                logger.warning("Failed to send error email: %s", e)

            return ServiceResponse(success="0", message="JDE returned ERROR. See logs/email for details")

        return ServiceResponse(success="1", message="OK")

    except Exception as e:
        logger.exception("create_fatture failed")
        return ServiceResponse(success="0", message=str(e))

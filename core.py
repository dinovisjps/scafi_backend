"""
core.py — settings, logging, request context, db pool, http/smtp helpers, readiness
"""
from __future__ import annotations

import os, json, time, random, socket, smtplib, logging, logging.handlers
from logging.config import dictConfig
from typing import Any, Dict, Optional, Tuple
from contextvars import ContextVar
from urllib.parse import urlparse

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# -------- Request context (adds X-Request-ID & client IP to every log line)
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="-")

class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        record.client_ip = client_ip_var.get("-")
        return True

def _getenv(key: str, default: Optional[str] = None) -> str:
    v = os.getenv(key, default)
    if v is None:
        raise RuntimeError(f"Missing required env var: {key}")
    return v

# -------- Logging config (file + console) with a single, unified format
LOG_PATH = os.getenv("LOG_PATH", "/home/webprod/logs/scafi_backend.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

def setup_logging() -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": { "ctx": {"()": RequestContextFilter} },
        "formatters": {
            "std": { "format": "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s ip=%(client_ip)s] %(message)s" }
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": LOG_PATH, "maxBytes": 10_000_000, "backupCount": 5,
                "formatter": "std", "filters": ["ctx"], "encoding": "utf-8"
            },
            "console": { "class": "logging.StreamHandler", "formatter": "std", "filters": ["ctx"] }
        },
        "root": { "handlers": ["file", "console"], "level": LOG_LEVEL },
        "loggers": {
            "uvicorn": {"level": LOG_LEVEL, "handlers": ["file", "console"], "propagate": False},
            "uvicorn.error": {"level": LOG_LEVEL, "handlers": ["file", "console"], "propagate": False},
            "uvicorn.access": {"level": LOG_LEVEL, "handlers": ["file", "console"], "propagate": False},
        }
    })

setup_logging()
log = logging.getLogger(__name__)

# -------- Env settings (DB / JDE / SMTP / timeouts / retries / dry-run flags)
DB_NAME   = _getenv("DB_NAME", "scafisoc")
DB_USER   = _getenv("DB_USER", "scafiadm")
DB_PASS   = _getenv("DB_PASS", "")
DB_HOST   = _getenv("DB_HOST", "127.0.0.1")
DB_PORT   = int(_getenv("DB_PORT", "5432"))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))
DB_STMT_TIMEOUT_MS = int(os.getenv("DB_STMT_TIMEOUT_MS", "8000"))
DB_LOCK_TIMEOUT_MS = int(os.getenv("DB_LOCK_TIMEOUT_MS", "3000"))
DB_POOL_MIN        = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX        = int(os.getenv("DB_POOL_MAX", "10"))

JDE_HOST     = os.getenv("JDE_HOST", "192.168.11.103")
JDE_PORT     = int(os.getenv("JDE_PORT", "8000"))
JDE_BASE_URL = os.getenv("JDE_BASE_URL", f"http://{JDE_HOST}:{JDE_PORT}")
JDE_PATH_ANAG= os.getenv("JDE_PATH_ANAG", "/api/anagrafiche")
JDE_PATH_FATT= os.getenv("JDE_PATH_FATT", "/api/fatture")
JDE_CREDENTIALS_JSON = os.getenv("JDE_CREDENTIALS_JSON")  # optional JSON

HTTP_TIMEOUT      = int(os.getenv("HTTP_TIMEOUT", "15"))
HTTP_RETRIES      = int(os.getenv("HTTP_RETRIES", "2"))
HTTP_BACKOFF_BASE = float(os.getenv("HTTP_BACKOFF_BASE", "0.3"))

SMTP_HOST       = os.getenv("SMTP_HOST", "127.0.0.1")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "25"))
SMTP_TIMEOUT    = int(os.getenv("SMTP_TIMEOUT", "5"))
SMTP_FROM       = os.getenv("SMTP_FROM", "noreply@scafi.it")
SMTP_TO_DEFAULT = tuple(filter(None, os.getenv("SMTP_TO_DEFAULT", "it@scafi.it").split(",")))

DRY_RUN_DB   = os.getenv("DRY_RUN_DB", "0") == "1"
DRY_RUN_JDE  = os.getenv("DRY_RUN_JDE", "0") == "1"
DRY_RUN_SMTP = os.getenv("DRY_RUN_SMTP", "1") == "1"

# -------- Postgres pool with timeouts and keepalives
_POOL: Optional[SimpleConnectionPool] = None

def init_db_pool() -> None:
    global _POOL
    if _POOL is not None or DRY_RUN_DB:
        if DRY_RUN_DB: log.warning("DB pool NOT initialized (DRY_RUN_DB=1)")
        return
    dsn = {
        "dbname": DB_NAME, "user": DB_USER, "password": DB_PASS, "host": DB_HOST, "port": DB_PORT,
        "connect_timeout": DB_CONNECT_TIMEOUT,
        "options": f"-c statement_timeout={DB_STMT_TIMEOUT_MS} -c lock_timeout={DB_LOCK_TIMEOUT_MS}",
        "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 5,
    }
    _POOL = SimpleConnectionPool(DB_POOL_MIN, DB_POOL_MAX, **dsn)
    log.info("DB pool initialized (min=%s max=%s host=%s db=%s)", DB_POOL_MIN, DB_POOL_MAX, DB_HOST, DB_NAME)

def get_db_conn():
    if DRY_RUN_DB: raise RuntimeError("DB disabled by DRY_RUN_DB")
    if _POOL is None: init_db_pool()
    assert _POOL is not None
    return _POOL.getconn()

def put_db_conn(conn) -> None:
    if DRY_RUN_DB: return
    assert _POOL is not None
    try: _POOL.putconn(conn)
    except Exception: log.exception("Returning connection to pool failed")

def close_db_pool() -> None:
    global _POOL
    if _POOL is not None:
        _POOL.closeall(); _POOL = None
        log.info("DB pool closed")

def db_ping(timeout_ms: int = 1000) -> bool:
    if DRY_RUN_DB: return True
    conn = None
    try:
        conn = get_db_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                cur.execute("SELECT 1"); cur.fetchone()
        return True
    except Exception as e:
        log.warning("DB ping failed: %s", e); return False
    finally:
        if conn: put_db_conn(conn)

# -------- HTTP client to JDE (stdlib, with timeout + retries + jittered backoff)
def _http_connection(parsed, timeout: int):
    import http.client
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout)
    return http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)

def http_json(method: str, base_url: str, path: str, payload: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None, timeout: int = HTTP_TIMEOUT,
              retries: int = HTTP_RETRIES) -> Tuple[int, Dict[str, Any]]:
    if DRY_RUN_JDE:
        log.info("DRY_RUN_JDE: %s %s", method, path); return 200, {"dry_run": True}

    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid JDE_BASE_URL: {base_url}")

    body_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    h = {"Content-Type": "application/json"}; h.update(headers or {})

    attempt = 0
    while True:
        attempt += 1
        try:
            conn = _http_connection(parsed, timeout)
            full_path = path if path.startswith("/") else f"/{path}"
            log.debug("HTTP %s %s%s attempt=%s", method, parsed.netloc, full_path, attempt)
            conn.request(method.upper(), full_path, body=body_bytes, headers=h)
            resp = conn.getresponse(); data = resp.read(); status = resp.status
            try: js = json.loads(data.decode("utf-8") if data else "{}")
            except Exception: js = {"raw": (data[:200] if data else b"").decode("utf-8", errors="replace")}
            log.debug("HTTP response status=%s", status)
            return status, js
        except (socket.timeout, ConnectionError, OSError) as e:
            if attempt > (1 + retries):
                log.warning("HTTP failed after %s attempts: %s", attempt - 1, e); raise
            sleep_s = HTTP_BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 0.2)
            log.warning("HTTP error (attempt %s): %s — retry in %.2fs", attempt, e, sleep_s)
            time.sleep(sleep_s)
        finally:
            try: conn.close()  # type: ignore
            except Exception: pass

def jde_ping(timeout: int = 3) -> bool:
    try:
        status, _ = http_json("GET", JDE_BASE_URL, "/health", None, timeout=timeout, retries=0)
        return 200 <= status < 500
    except Exception as e:
        log.warning("JDE ping failed: %s", e); return False

# -------- SMTP helper (short timeout; DRY-RUN by default)
def send_mail(subject: str, body: str, to: Tuple[str, ...] = SMTP_TO_DEFAULT) -> None:
    if DRY_RUN_SMTP:
        log.info("DRY_RUN_SMTP: mail suppressed subject=%s to=%s", subject, ",".join(to)); return
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as s:
            msg = f"Subject: {subject}\nFrom: {SMTP_FROM}\nTo: {', '.join(to)}\n\n{body}"
            s.sendmail(SMTP_FROM, list(to), msg)
        log.info("Mail sent to %s: %s", ",".join(to), subject)
    except Exception:
        log.exception("Mail send failed")

# -------- Aggregated readiness
def is_ready() -> bool:
    ok_db = db_ping(); ok_jde = jde_ping()
    log.debug("Readiness check db=%s jde=%s", ok_db, ok_jde)
    return ok_db and ok_jde

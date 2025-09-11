## Scafi Backend Integration

FastAPI-based backend providing integration endpoints for Anagrafiche and Fatture with health/readiness checks, logging, Postgres, simple HTTP client, and optional SMTP.

### Requirements
- Python 3.11+
- PostgreSQL (unless running with `DRY_RUN_DB=1`)

### Quick start
```bash
# From repo root
cd /home/debian/ORACLE/new_scafiBackend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Environment configuration
This app uses `python-dotenv` and automatically loads variables from `/home/debian/ORACLE/new_scafiBackend/.env` at startup. Create the file and set values as needed.

Minimal example for local development (INFO logs, dry-run everything):
```bash
# /home/debian/ORACLE/new_scafiBackend/.env
LOG_LEVEL=INFO
LOG_PATH=/home/debian/ORACLE/new_scafiBackend/logs/logs.log

# Database (unused if DRY_RUN_DB=1)
DB_NAME=scafisoc
DB_USER=scafiadm
DB_PASS=
DB_HOST=127.0.0.1
DB_PORT=5432
DB_CONNECT_TIMEOUT=5
DB_STMT_TIMEOUT_MS=8000
DB_LOCK_TIMEOUT_MS=3000
DB_POOL_MIN=1
DB_POOL_MAX=10

# JDE HTTP
JDE_HOST=192.168.11.103
JDE_PORT=8000
# JDE_BASE_URL=http://192.168.11.103:8000
JDE_PATH_ANAG=/api/anagrafiche
JDE_PATH_FATT=/api/fatture
# JDE_CREDENTIALS_JSON={"username":"u","password":"p"}

# HTTP client
HTTP_TIMEOUT=15
HTTP_RETRIES=2
HTTP_BACKOFF_BASE=0.3

# SMTP
SMTP_HOST=127.0.0.1
SMTP_PORT=25
SMTP_TIMEOUT=5
SMTP_FROM=noreply@scafi.it
SMTP_TO_DEFAULT=it@scafi.it

# Dry-run flags
DRY_RUN_DB=1
DRY_RUN_JDE=1
DRY_RUN_SMTP=1
```

Notes:
- Process environment variables take precedence over `.env` values (the loader uses `override=False`).
- `.env` is ignored by git (see `.gitignore`).

### Run (development)
Use uvicorn with auto-reload:
```bash
# From repo root with venv activated
uvicorn app:app --reload --host 0.0.0.0 --port 8001
```

### Run (production)
Run uvicorn directly with multiple workers (simple, no process manager):
```bash
# Adjust workers to CPU cores; set a sensible timeout
uvicorn app:app \
  --host 0.0.0.0 \
  --port 8001 \
  --workers 4 \
  --log-level info
```

Or via systemd (recommended on Linux):
```ini
# /etc/systemd/system/scafi-backend.service
[Unit]
Description=Scafi Backend (FastAPI)
After=network.target

[Service]
WorkingDirectory=/home/debian/ORACLE/new_scafiBackend
Environment="PATH=/home/debian/ORACLE/new_scafiBackend/.venv/bin"
# Ensure your .env exists at the project path
ExecStart=/home/debian/ORACLE/new_scafiBackend/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info
Restart=always
RestartSec=5
User=debian
Group=debian

[Install]
WantedBy=multi-user.target
```
Then enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scafi-backend
sudo systemctl status scafi-backend | cat
```

### Endpoints
- Health: `GET /healthz` → `{ "status": "ok" }`
- Readiness: `GET /readyz` → checks DB and JDE reachability
- Create Anagrafiche: `POST /integration/anagrafiche`
- Create Fatture: `POST /integration/fatture`

### Logging
- Default log level is INFO (configurable via `LOG_LEVEL`).
- Logs are written to file at `LOG_PATH` and to console. Each line includes request id and client IP.

### Troubleshooting
- DB disabled: set `DRY_RUN_DB=1` to run without a database.
- JDE disabled: set `DRY_RUN_JDE=1` to avoid external HTTP calls.
- Email disabled: set `DRY_RUN_SMTP=1` to suppress emails.
- If `.env` changes aren't picked up, ensure the file path is `/home/debian/ORACLE/new_scafiBackend/.env` and restart the process.

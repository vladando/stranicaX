    from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import uuid
from datetime import datetime
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from concurrent.futures import ThreadPoolExecutor
import socket
import time

app = Flask(__name__)
CORS(app)

# ------------------------ PERSISTENT STORAGE ------------------------
# Ako na Renderu dodaš Disk montiran na /data, fajl će preživeti redeploy-e.
DATA_FILE = os.getenv("DATA_FILE", "/data/submissions.json")
PROMPT_DIR = os.getenv("PROMPT_DIR", "prompts")

RATE_LIMIT = 5
REQUESTS = {}

# ------------------------ SMTP CONFIG ------------------------
# Postavi u Render → Settings → Environment Variables
SMTP_SERVER = os.getenv("SMTP_SERVER", "mail.stranicax.com")
# Redosled pokušaja; preporučeno: 2525 prvi (kod tebe radi), zatim 587/465
SMTP_PORTS = [int(p.strip()) for p in os.getenv("SMTP_PORTS", "2525,587,465").split(",") if p.strip()]
SMTP_USER = os.getenv("SMTP_USER", "kontakt@stranicax.com")
SMTP_PASS = os.getenv("SMTP_PASS", "TVOJA_LOZINKA")
TARGET_EMAIL = os.getenv("TARGET_EMAIL", "vlasnik@stranicax.com")  # ako ownerEmail nije poslat/validan

SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "12"))
SMTP_RETRIES = int(os.getenv("SMTP_RETRIES", "2"))
RETRY_SLEEP = float(os.getenv("SMTP_RETRY_SLEEP", "0.5"))
EMAIL_WORKERS = int(os.getenv("EMAIL_WORKERS", "2"))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME_LEN = 200
MAX_EMAIL_LEN = 320
MAX_MSG_LEN = 8000

EMAIL_JOBS = {}

# ------------------------ INIT FS ------------------------
os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)
os.makedirs(PROMPT_DIR, exist_ok=True)

executor = ThreadPoolExecutor(max_workers=EMAIL_WORKERS)


def safe_trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n]


def _send_via_starttls(port: int, msg):
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, port, timeout=SMTP_TIMEOUT) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.ehlo()

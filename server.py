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
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def _send_via_smtps_465(msg):
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, 465, context=ctx, timeout=SMTP_TIMEOUT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def send_email_with_fallback(to_addr: str, subject: str, body: str, reply_to: str = None):
    """
    Pokušaj slanje kroz više portova, s kratkim retry-jem.
    Dodata 'Date' i 'Message-ID' zaglavlja radi deliverability-ja.
    """
    msg = MIMEMultipart()
    msg["From"] = f"StranicaX Kontakt <{SMTP_USER}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    # Forsira domen u Message-ID radi boljeg sklada sa DKIM/DMARC
    msg["Message-ID"] = make_msgid(domain="stranicax.com")
    if reply_to:
        msg.add_header("Reply-To", reply_to)
    msg.attach(MIMEText(body, "plain"))

    last_err = None
    for attempt in range(1, SMTP_RETRIES + 1):
        for port in SMTP_PORTS:
            try:
                if port == 465:
                    _send_via_smtps_465(msg)
                else:
                    _send_via_starttls(port, msg)
                return  # uspeh
            except (socket.timeout, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as e:
                last_err = f"timeout/connect on port {port}: {e}"
                print(f"[EMAIL] attempt {attempt} port {port}: {last_err}")
            except Exception as e:
                last_err = f"error on port {port}: {e}"
                print(f"[EMAIL] attempt {attempt} port {port}: {last_err}")
        time.sleep(RETRY_SLEEP)
    raise RuntimeError(last_err or "Unknown SMTP error")


def queue_email(job_id: str, to_addr: str, subject: str, body: str, reply_to: str = None):
    EMAIL_JOBS[job_id] = {"status": "queued", "error": None, "to": to_addr, "ts": datetime.utcnow().isoformat()}

    def _run():
        try:
            EMAIL_JOBS[job_id]["status"] = "sending"
            send_email_with_fallback(to_addr, subject, body, reply_to)
            EMAIL_JOBS[job_id]["status"] = "sent"
        except Exception as e:
            EMAIL_JOBS[job_id]["status"] = "failed"
            EMAIL_JOBS[job_id]["error"] = str(e)
            print(f"[EMAIL][{job_id}] error: {e}")

    executor.submit(_run)


# ------------------------ SUBMISSION API ------------------------

def _load_all():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[LOAD_ALL] error: {e}")
        return []


def _save_all(all_data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[SAVE_ALL] error: {e}")


def save_submission(data, client_ip):
    all_data = _load_all()
    submission = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "ip": client_ip,
        "data": data,
        "processed": False,
        "result_url": None
    }
    all_data.append(submission)
    _save_all(all_data)
    return submission["id"]


def mark_submission_processed(submission_id, result_url=None):
    all_data = _load_all()
    found = False
    for s in all_data:
        if s["id"] == submission_id:
            s["processed"] = True
            if result_url:
                s["result_url"] = result_url
            found = True
            break
    if found:
        _save_all(all_data)
    return found


@app.route('/submit-form', methods=['POST'])
def receive_form():
    """Prima podatke sa fronta, kreira submission_id i snima u submissions.json."""
    try:
        data = request.json
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)

        if client_ip not in REQUESTS:
            REQUESTS[client_ip] = 0
        if REQUESTS[client_ip] >= RATE_LIMIT:
            return jsonify({"status": "error", "message": "Previše zahtjeva sa ove IP adrese"}), 429
        REQUESTS[client_ip] += 1

        submission_id = save_submission(data, client_ip)
        return jsonify({"status": "success", "submission_id": submission_id, "ip": client_ip})
    except Exception as e:
        print("Greška (submit-form):", str(e))
        return jsonify({"status": "error", "message": "Neočekivana greška na serveru"}), 500


@app.route('/get-new-submissions', methods=['GET'])
def get_new_submissions():
    """Vraća sve NEobrađene zahtjeve (čita ih tvoj worker)."""
    try:
        all_data = _load_all()
        new_submissions = [s for s in all_data if not s.get("processed", False)]
        return jsonify({"status": "success", "submissions": new_submissions})
    except Exception as e:
        print("Greška (get-new-submissions):", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/mark-processed/<submission_id>', methods=['POST'])
def mark_processed(submission_id):
    """Pozove je worker nakon što generiše sajt; setuje processed=True i (opciono) result_url."""
    try:
        data = request.json or {}
        result_url = data.get("result_url")
        if mark_submission_processed(submission_id, result_url):
            return jsonify({"status": "success", "message": f"Submission {submission_id} marked as processed"})
        else:
            return jsonify({"status": "error", "message": "Submission not found"}), 404
    except Exception as e:
        print("Greška (mark-processed):", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/status/<submission_id>', methods=['GET'])
def status(submission_id):
    """Frontend polling: vrati processed/result_url za dati submission_id."""
    try:
        all_data = _load_all()
        for s in all_data:
            if s["id"] == submission_id:
                return jsonify({
                    "status": "success",
                    "submission_id": submission_id,
                    "processed": bool(s.get("processed", False)),
                    "result_url": s.get("result_url")
                })
        return jsonify({"status": "error", "message": "Submission not found"}), 404
    except Exception as e:
        print("Greška (status):", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


# ------------------------ EMAIL API ------------------------

@app.route('/send-email', methods=['POST'])
def send_email():
    """
    Prima podatke iz kontakt forme i queue-uje slanje emaila u pozadini.
    Podržava JSON i x-www-form-urlencoded. Odmah vraća success (ne blokira HTTP).
    """
    try:
        data = request.get_json(silent=True) if request.is_json else None
        if data is None:
            data = request.form.to_dict()

        sender_name = safe_trim(data.get("name"), MAX_NAME_LEN)
        sender_email = safe_trim(data.get("email"), MAX_EMAIL_LEN)
        message_text = safe_trim(data.get("message"), MAX_MSG_LEN)

        owner_email = safe_trim(data.get("ownerEmail"), MAX_EMAIL_LEN)
        to_addr = owner_email if EMAIL_RE.match(owner_email) else TARGET_EMAIL

        if not sender_name or not EMAIL_RE.match(sender_email) or not message_text:
            return jsonify({"status": "error", "message": "Neispravna ili prazna polja (name/email/message)."}), 400

        subject = f"Nova poruka sa sajta od {sender_name}"
        body = (
            "Nova poruka preko kontakt forme:\n\n"
            f"Ime: {sender_name}\n"
            f"Email: {sender_email}\n\n"
            "Poruka:\n"
            f"{message_text}\n"
        )

        job_id = str(uuid.uuid4())
        queue_email(job_id, to_addr, subject, body, reply_to=sender_email)
        return jsonify({"status": "success", "queued": True, "job_id": job_id}), 200

    except (socket.timeout, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as e:
        print("SMTP timeout/disconnect:", str(e))
        return jsonify({"status": "error", "message": "SMTP timeout/disconnect"}), 504
    except Exception as e:
        print("Greška pri slanju emaila:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/email-status/<job_id>', methods=['GET'])
def email_status(job_id):
    info = EMAIL_JOBS.get(job_id)
    if not info:
        return jsonify({"status": "unknown", "job_id": job_id}), 404
    return jsonify({"status": info["status"], "error": info.get("error"), "job_id": job_id})


# ------------------------ HEALTH ------------------------

def _probe_port(port: int) -> dict:
    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_SERVER, 465, context=ctx, timeout=5) as s:
                s.noop()
            return {"port": port, "ok": True, "mode": "smtps"}
        else:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(SMTP_SERVER, port, timeout=5) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
            return {"port": port, "ok": True, "mode": "starttls"}
    except Exception as e:
        return {"port": port, "ok": False, "error": str(e)}


@app.route('/smtp-health', methods=['GET'])
def smtp_health():
    results = []
    for p in SMTP_PORTS:
        results.append(_probe_port(p))
    return jsonify({"server": SMTP_SERVER, "results": results}), 200


@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Server radi!"}), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)

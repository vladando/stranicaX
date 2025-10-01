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
from concurrent.futures import ThreadPoolExecutor
import socket
import time

app = Flask(__name__)
CORS(app)

DATA_FILE = 'submissions.json'
PROMPT_DIR = 'prompts'
RATE_LIMIT = 5
REQUESTS = {}

# --- SMTP CONFIG (možeš postaviti kroz env na Render-u) ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "mail.stranicax.com")
# Poredak pokušaja (587 STARTTLS → 465 SMTPS); možeš promeniti kroz env, npr. "465,587"
SMTP_PORTS = [int(p.strip()) for p in os.getenv("SMTP_PORTS", "587,465").split(",") if p.strip()]
SMTP_USER = os.getenv("SMTP_USER", "kontakt@stranicax.com")
SMTP_PASS = os.getenv("SMTP_PASS", "TVOJA_LOZINKA")
TARGET_EMAIL = os.getenv("TARGET_EMAIL", "vlasnik@stranicax.com")  # fallback ako ownerEmail nije poslat/ispravan

SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "12"))  # kratak da ne blokira workere
SMTP_RETRIES = int(os.getenv("SMTP_RETRIES", "2"))
RETRY_SLEEP = float(os.getenv("SMTP_RETRY_SLEEP", "1.0"))

EMAIL_WORKERS = int(os.getenv("EMAIL_WORKERS", "2"))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME_LEN = 200
MAX_EMAIL_LEN = 320
MAX_MSG_LEN = 8000

EMAIL_JOBS = {}
os.makedirs(PROMPT_DIR, exist_ok=True)
executor = ThreadPoolExecutor(max_workers=EMAIL_WORKERS)


def safe_trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n]


def _send_via_587_starttls(msg):
    """Pokušaj preko 587 sa STARTTLS."""
    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, 587, timeout=SMTP_TIMEOUT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def _send_via_465_smtps(msg):
    """Pokušaj preko 465 (SMTPS/SSL wrap)."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, 465, context=context, timeout=SMTP_TIMEOUT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def send_email_with_fallback(to_addr: str, subject: str, body: str, reply_to: str = None):
    """Pokušaj slanje na više portova sa kratkim retry-jem."""
    msg = MIMEMultipart()
    msg["From"] = f"StranicaX Kontakt <{SMTP_USER}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    if reply_to:
        msg.add_header("Reply-To", reply_to)
    msg.attach(MIMEText(body, "plain"))

    last_err = None
    for attempt in range(1, SMTP_RETRIES + 1):
        for port in SMTP_PORTS:
            try:
                if port == 587:
                    _send_via_587_starttls(msg)
                elif port == 465:
                    _send_via_465_smtps(msg)
                else:
                    # Ako dodaš drugi port, tretiraj ga kao STARTTLS
                    context = ssl.create_default_context()
                    with smtplib.SMTP(SMTP_SERVER, port, timeout=SMTP_TIMEOUT) as server:
                        server.ehlo()
                        server.starttls(context=context)
                        server.ehlo()
                        server.login(SMTP_USER, SMTP_PASS)
                        server.send_message(msg)
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

def save_submission(data, client_ip):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    else:
        all_data = []

    submission = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "ip": client_ip,
        "data": data,
        "processed": False,
        "result_url": None
    }
    all_data.append(submission)

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    return submission["id"]


def mark_submission_processed(submission_id, result_url=None):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
        for submission in all_data:
            if submission["id"] == submission_id:
                submission["processed"] = True
                if result_url:
                    submission["result_url"] = result_url
                break
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        return True
    return False


@app.route('/submit-form', methods=['POST'])
def receive_form():
    try:
        data = request.json
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)

        if client_ip not in REQUESTS:
            REQUESTS[client_ip] = 0
        if REQUESTS[client_ip] >= RATE_LIMIT:
            return jsonify({"status": "error", "message": "Previše zahtjeva sa ove IP adrese"}), 429
        REQUESTS[client_ip] += 1

        submission_id = save_submission(data, client_ip)

        return jsonify({
            "status": "success",
            "submission_id": submission_id,
            "ip": client_ip
        })
    except Exception as e:
        print("Greška (submit-form):", str(e))
        return jsonify({"status": "error", "message": "Neočekivana greška na serveru"}), 500


@app.route('/get-new-submissions', methods=['GET'])
def get_new_submissions():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
            new_submissions = [s for s in all_data if not s.get("processed", False)]
            return jsonify({"status": "success", "submissions": new_submissions})
        else:
            return jsonify({"status": "success", "submissions": []})
    except Exception as e:
        print("Greška (get-new-submissions):", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/mark-processed/<submission_id>', methods=['POST'])
def mark_processed(submission_id):
    try:
        data = request.json or {}
        result_url = data.get("result_url")
        success = mark_submission_processed(submission_id, result_url)
        if success:
            return jsonify({"status": "success", "message": f"Submission {submission_id} marked as processed"})
        else:
            return jsonify({"status": "error", "message": "Submission not found"}), 404
    except Exception as e:
        print("Greška (mark-processed):", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


# ------------------------ EMAIL API ------------------------

@app.route('/send-email', methods=['POST'])
def send_email():
    """
    Prima podatke iz kontakt forme i queue-uje slanje emaila u pozadini.
    Podržava JSON i form-data. Odmah vraća success (ne blokira HTTP).
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
    # 587 test STARTTLS handshake, 465 test SSL connect
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

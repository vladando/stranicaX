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
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)
CORS(app)  # dozvoli frontove sa svih domena

DATA_FILE = 'submissions.json'
PROMPT_DIR = 'prompts'
RATE_LIMIT = 5  # max zahtjeva po IP (za submit-form)
REQUESTS = {}   # memorijski brojač

# --- SMTP konfiguracija (čitaj iz env gde može) ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "mail.stranicax.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "kontakt@stranicax.com")
SMTP_PASS = os.getenv("SMTP_PASS", "TVOJA_LOZINKA")
TARGET_EMAIL = os.getenv("TARGET_EMAIL", "vlasnik@stranicax.com")  # fallback ako nije poslat ownerEmail

SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "15"))
EMAIL_WORKERS = int(os.getenv("EMAIL_WORKERS", "2"))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME_LEN = 200
MAX_EMAIL_LEN = 320
MAX_MSG_LEN = 8000

# jednostavna memorijska mapa statusa poslatih mejlova (samo za brzi uvid)
EMAIL_JOBS = {}

# kreiraj folder za promptove ako ne postoji
os.makedirs(PROMPT_DIR, exist_ok=True)

# thread pool za non-blocking slanje
executor = ThreadPoolExecutor(max_workers=EMAIL_WORKERS)


def safe_trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n]


def send_email_smtp(to_addr: str, subject: str, body: str, reply_to: str = None) -> None:
    """Realno slanje mejla preko SMTP-a (poziva se u pozadini)."""
    msg = MIMEMultipart()
    msg["From"] = f"StranicaX Kontakt <{SMTP_USER}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    if reply_to:
        msg.add_header("Reply-To", reply_to)
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def queue_email(job_id: str, to_addr: str, subject: str, body: str, reply_to: str = None):
    """Stavi slanje u pozadinu, status čuvamo u memoriji (best-effort)."""
    EMAIL_JOBS[job_id] = {"status": "queued", "error": None, "to": to_addr, "ts": datetime.utcnow().isoformat()}

    def _run():
        try:
            EMAIL_JOBS[job_id]["status"] = "sending"
            send_email_smtp(to_addr, subject, body, reply_to)
            EMAIL_JOBS[job_id]["status"] = "sent"
        except Exception as e:
            EMAIL_JOBS[job_id]["status"] = "failed"
            EMAIL_JOBS[job_id]["error"] = str(e)
            print(f"[EMAIL][{job_id}] error: {e}")

    executor.submit(_run)


# ------------------------ SUBMISSION API ------------------------

def save_submission(data, client_ip):
    """Čuva zahtjev u JSON fajl."""
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
    """Označava zahtjev kao obrađen i dodaje link."""
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
    """Prima formu sa frontenda, kreira submission_id i čuva podatke."""
    try:
        data = request.json
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)

        # Rate limiting po IP
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
    """Vraća sve neobrađene zahtjeve (koristi Selenium/worker)."""
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
    """Poziva ga obrada kada završi sajt i dodaje link."""
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
    Prima podatke iz kontakt forme i 'queue'-uje slanje emaila u pozadini.
    Podržava JSON i form-data. Odmah vraća success (ne blokira HTTP).
    """
    try:
        # Prihvati JSON ili klasičnu HTML formu
        data = request.get_json(silent=True) if request.is_json else None
        if data is None:
            data = request.form.to_dict()

        # Polja iz forme
        sender_name = safe_trim(data.get("name"), MAX_NAME_LEN)
        sender_email = safe_trim(data.get("email"), MAX_EMAIL_LEN)
        message_text = safe_trim(data.get("message"), MAX_MSG_LEN)

        # Dinamični vlasnikov mejl iz forme (skriveno polje). Fallback na TARGET_EMAIL
        owner_email = safe_trim(data.get("ownerEmail"), MAX_EMAIL_LEN)
        to_addr = owner_email if EMAIL_RE.match(owner_email) else TARGET_EMAIL

        # Validacija
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

        # Queue posao
        job_id = str(uuid.uuid4())
        queue_email(job_id, to_addr, subject, body, reply_to=sender_email)

        # Odmah odgovori da je uspešno prihvaćeno (ne čeka SMTP)
        return jsonify({"status": "success", "queued": True, "job_id": job_id}), 200

    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError) as e:
        print("SMTP timeout/disconnect:", str(e))
        return jsonify({"status": "error", "message": "SMTP timeout/disconnect"}), 504
    except Exception as e:
        print("Greška pri slanju emaila:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/email-status/<job_id>', methods=['GET'])
def email_status(job_id):
    """Best-effort status za queued email (u memoriji procesa)."""
    info = EMAIL_JOBS.get(job_id)
    if not info:
        return jsonify({"status": "unknown", "job_id": job_id}), 404
    return jsonify({"status": info["status"], "error": info.get("error"), "job_id": job_id})


# ------------------------ HEALTH ------------------------

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Server radi!"}), 200


@app.route('/smtp-health', methods=['GET'])
def smtp_health():
    """Brz test da li se možemo spojiti na SMTP (bez slanja poruke)."""
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=min(SMTP_TIMEOUT, 5)) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            # ne logujemo se i ne šaljemo, dovoljna je TLS ruka
        return jsonify({"status": "ok", "smtp": f"{SMTP_SERVER}:{SMTP_PORT}"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)

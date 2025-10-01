from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
import uuid
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
CORS(app)  # Dozvoljava frontend sa svih domena

DATA_FILE = 'submissions.json'
PROMPT_DIR = 'prompts'
RATE_LIMIT = 5  # max zahtjeva po IP
REQUESTS = {}   # memorijski brojač

# --- SMTP konfiguracija ---
SMTP_SERVER = "mail.stranicax.com"   # ili "localhost" ako koristiš Postfix na VPS-u
SMTP_PORT = 587                      # 587 za TLS (465 za SSL)
SMTP_USER = "kontakt@stranicax.com"  # mejl nalog koji si kreirao
SMTP_PASS = "TVOJA_LOZINKA"          # lozinka tog naloga
TARGET_EMAIL = "vlasnik@stranicax.com"  # gde vlasnik prima poruke sa sajta


# Kreiraj folder za promptove ako ne postoji
if not os.path.exists(PROMPT_DIR):
    os.makedirs(PROMPT_DIR)


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

        # Rate limiting
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
        print("Greška:", str(e))
        return jsonify({"status": "error", "message": "Neočekivana greška na serveru"}), 500


@app.route('/get-new-submissions', methods=['GET'])
def get_new_submissions():
    """Vraća sve neobrađene zahtjeve (koristi Selenium worker)."""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
            new_submissions = [s for s in all_data if not s.get("processed", False)]
            return jsonify({"status": "success", "submissions": new_submissions})
        else:
            return jsonify({"status": "success", "submissions": []})
    except Exception as e:
        print("Greška:", str(e))
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
        print("Greška:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/status/<submission_id>', methods=['GET'])
def get_status(submission_id):
    """Frontend provjerava status obrade i eventualni URL."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
        for submission in all_data:
            if submission["id"] == submission_id:
                return jsonify({
                    "status": "success",
                    "submission_id": submission_id,
                    "processed": submission.get("processed", False),
                    "result_url": submission.get("result_url", None)
                })
    return jsonify({"status": "error", "message": "Submission not found"}), 404


# --- NOVO: slanje mejlova ---
@app.route('/send-email', methods=['POST'])
def send_email():
    """Prima podatke iz kontakt forme i šalje email vlasniku sajta."""
    try:
        data = request.json
        sender_name = data.get("name")
        sender_email = data.get("email")
        message_text = data.get("message")

        msg = MIMEMultipart()
        msg["From"] = f"StranicaX Kontakt <{SMTP_USER}>"
        msg["To"] = TARGET_EMAIL
        msg["Subject"] = f"Nova poruka sa sajta od {sender_name}"
        msg.add_header("Reply-To", sender_email)

        body = f"""
        Nova poruka preko kontakt forme:

        Ime: {sender_name}
        Email: {sender_email}

        Poruka:
        {message_text}
        """
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        return jsonify({"status": "success", "message": "Email uspešno poslat!"}), 200

    except Exception as e:
        print("Greška pri slanju emaila:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Server radi!"}), 200


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)

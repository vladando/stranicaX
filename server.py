from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os

app = Flask(__name__)
CORS(app)

DATA_FILE = 'submissions.json'

def save_submission(data):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    else:
        all_data = []
    all_data.append(data)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

def build_deepsite_prompt(data):
    services = "\n".join(
        [f"- {s['name']} ({s['price']}): {s['description']}" for s in data.get('services', [])]
    )
    team = "\n".join(
        [f"- {m['name']} — {m['position']}: {m['bio']}" for m in data.get('teamMembers', [])]
    )
    prompt = f"""
Napravi modernu i profesionalnu web stranicu koristeći :contentReference[oaicite:2]{index=2} za sljedeću firmu:

Naziv: {data.get('companyName')}
Slogan: {data.get('slogan')}
Opis: {data.get('companyDescription')}
Djelatnost: {data.get('industry')}
Godina osnivanja: {data.get('yearFounded')}
Broj zaposlenih: {data.get('employees')}
Email: {data.get('email')}
Telefon: {data.get('phone')}
Facebook: {data.get('facebook')}
Instagram: {data.get('instagram')}
LinkedIn: {data.get('linkedin')}

Usluge:
{services}

Tim:
{team}

Glavna boja: {data.get('primaryColor')}
Sekundarna boja: {data.get('secondaryColor')}
Stil dizajna: {data.get('style')}
Font: {data.get('font')}
Jezik sajta: {data.get('language')}
Stranice: {', '.join(data.get('pages', []))}

Logo: {data.get('logo')}
Slike: {', '.join(data.get('images', []))}
Slike članova tima: {', '.join(data.get('memberPhotos', []))}

Dodatne napomene: {data.get('notes')}
"""
    return prompt.strip()

@app.route('/submit-form', methods=['POST'])
def receive_form():
    data = request.json
    print("Primljeni podaci:", data)

    # snimi podatke u fajl
    save_submission(data)

    # napravi prompt
    prompt = build_deepsite_prompt(data)

    return jsonify({"status": "success", "prompt": prompt})

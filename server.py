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
        [f"- {s['service-title']} ({s.get('service-price', 'Nije navedena cena')}): {s['service-description']}" 
         for s in data.get('services', [])]
    )
    team = "\n".join(
        [f"- {m['team-name']} — {m['team-position']}: {m.get('team-bio', 'Nije navedena biografija')}" 
         for m in data.get('teamMembers', [])]
    )
    portfolio = "\n".join(
        [f"- {p['project-name']}: {p.get('project-description', 'Nije naveden opis')}" 
         for p in data.get('portfolio', [])]
    )
    social_media = "\n".join(
        [f"{key.capitalize()}: {value}" for key, value in {
            'facebook': data.get('facebook', ''),
            'twitter': data.get('twitter', ''),
            'instagram': data.get('instagram', ''),
            'linkedin': data.get('linkedin', '')
        }.items() if value]
    )

    prompt = f"""
Napravi modernu i profesionalnu veb stranicu za sledeću firmu:

Naziv firme: {data.get('company-name', 'Nije navedeno')}
Slogan: {data.get('slogan', 'Nije navedeno')}
Opis: {data.get('description', 'Nije navedeno')}
Delatnost: {data.get('industry', 'Nije navedeno')}
Godina osnivanja: {data.get('year-founded', 'Nije navedeno')}
Broj zaposlenih: {data.get('num-employees', 'Nije navedeno')}
Kontakt:
- Email: {data.get('email', 'Nije navedeno')}
- Telefon: {data.get('phone', 'Nije navedeno')}
- Adresa: {data.get('address', 'Nije navedena')}
Društvene mreže:
{social_media if social_media else 'Nije navedeno'}
Radno vreme: {data.get('working-hours', 'Nije navedeno')}
Lokacija na mapi: {data.get('map-embed', 'Nije navedeno')}

Usluge/Proizvodi:
{services if services else 'Nije navedeno'}

Portfolio:
{portfolio if portfolio else 'Nije navedeno'}

Tim:
{team if team else 'Nije navedeno'}

Kultura firme: {data.get('culture', 'Nije navedeno')}

Vizuelni identitet:
- Logo: {data.get('logo-url', 'Nije navedeno')}
- Glavna boja: {data.get('primary-color', 'Nije navedeno')}
- Sekundarna boja: {data.get('secondary-color', 'Nije navedeno')}
- Stil dizajna: {data.get('style', 'Nije navedeno')}
- Font: {data.get('font', 'Nije navedeno')}
- Dodatne slike: {', '.join(data.get('additional-images', [])) if data.get('additional-images') else 'Nije navedeno'}

Stranice sajta: {', '.join(data.get('pages', [])) if data.get('pages') else 'Nije navedeno'}
Jezik sajta: {data.get('language', 'Nije navedeno')}
Registracija domena: {data.get('domain', 'Ne')} ({data.get('domain-address', 'Nije navedeno')})
Hosting: {data.get('hosting', 'Ne')}
Dodatne napomene: {data.get('notes', 'Nije navedeno')}
"""
    return prompt.strip()

@app.route('/submit-form', methods=['POST'])
def receive_form():
    data = request.json
    print("Primljeni podaci:", data)

    # Snimi podatke u fajl
    save_submission(data)

    # Napravi prompt
    prompt = build_deepsite_prompt(data)

    return jsonify({"status": "success", "prompt": prompt})

if __name__ == '__main__':
    app.run(debug=True)
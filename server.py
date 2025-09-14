from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os

app = Flask(__name__)
CORS(app, resources={r"/submit-form": {"origins": "https://enzostvs-deepsite.hf.space"}})

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
    # Validacija obaveznih polja
    required_fields = ['companyName', 'email']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        raise ValueError(f"Nedostaju obavezna polja: {', '.join(missing_fields)}")

    services = "\n".join(
        [f"- {s['name']} ({s.get('price', 'Nije navedena cena')}): {s['description']}" 
         for s in data.get('services', [])]
    )
    team = "\n".join(
        [f"- {m['name']} — {m['position']}: {m.get('bio', 'Nije navedena biografija')}" 
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

Naziv firme: {data.get('companyName', 'Nije navedeno')}
Slogan: {data.get('slogan', 'Nije navedeno')}
Opis: {data.get('companyDescription', 'Nije navedeno')}
Delatnost: {data.get('industry', 'Nije navedeno')}
Godina osnivanja: {data.get('yearFounded', 'Nije navedeno')}
Broj zaposlenih: {data.get('employees', 'Nije navedeno')}
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
- Logo: {data.get('logo', 'Nije navedeno')}
- Glavna boja: {data.get('primaryColor', 'Nije navedeno')}
- Sekundarna boja: {data.get('secondaryColor', 'Nije navedeno')}
- Stil dizajna: {data.get('style', 'Nije navedeno')}
- Font: {data.get('font', 'Nije navedeno')}
- Dodatne slike: {', '.join(data.get('images', [])) if data.get('images') else 'Nije navedeno'}

Stranice sajta: {', '.join(data.get('pages', [])) if data.get('pages') else 'Nije navedeno'}
Jezik sajta: {data.get('language', 'Nije navedeno')}
Registracija domena: {data.get('hasDomain', 'Ne')} ({data.get('domain', 'Nije navedeno')})
Hosting: {data.get('hasHosting', 'Ne')}
Dodatne napomene: {data.get('notes', 'Nije navedeno')}
"""
    return prompt.strip()

@app.route('/submit-form', methods=['POST'])
def receive_form():
    try:
        data = request.json
        print("Primljeni podaci:", data)

        # Snimi podatke u fajl
        save_submission(data)

        # Napravi prompt
        prompt = build_deepsite_prompt(data)

        return jsonify({"status": "success", "prompt": prompt})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": "Neočekivana greška na serveru"}), 500

if __name__ == '__main__':
    app.run(debug=True)
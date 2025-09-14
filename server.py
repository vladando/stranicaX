from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json, os

app = Flask(__name__)
CORS(app, resources={r"/submit-form": {"origins": "https://enzostvs-deepsite.hf.space"}})

DATA_FILE = 'submissions.json'
PROMPT_DIR = 'prompts'

# Kreiraj folder za promptove ako ne postoji
if not os.path.exists(PROMPT_DIR):
    os.makedirs(PROMPT_DIR)

def save_submission(data):
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    else:
        all_data = []
    all_data.append(data)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

def save_prompt_to_txt(company_name, prompt):
    # Kreiraj sigurno ime fajla
    safe_company_name = company_name.lower().replace(' ', '-').replace('/', '-').replace('\\', '-')
    file_name = f"{PROMPT_DIR}/{safe_company_name}-prompt.txt"
    with open(file_name, 'w', encoding='utf-8') as f:
        f.write(prompt)
    return file_name

def build_deepsite_prompt(data):
    # Validacija obaveznih polja
    required_fields = ['companyName', 'email']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        raise ValueError(f"Nedostaju obavezna polja: {', '.join(missing_fields)}")

    # Definisanje dozvoljenih polja za JSON
    allowed_fields = [
        'companyName', 'slogan', 'generateSlogan', 'companyDescription', 'industry', 
        'yearFounded', 'employees', 'email', 'phone', 'facebook', 'instagram', 'linkedin', 
        'services', 'generateImages', 'teamMembers', 'primaryColor', 'secondaryColor', 
        'style', 'font', 'pages', 'language', 'hasDomain', 'domain', 'hasHosting', 
        'notes', 'logo', 'images', 'memberPhotos'
    ]
    # Filtriranje samo dozvoljenih polja
    filtered_data = {k: data.get(k) for k in allowed_fields if k in data}

    services = "\n".join(
        [f"- {s['name']} ({s.get('price', 'Nije navedena cena')}): {s['description']}" 
         for s in filtered_data.get('services', [])]
    )
    team = "\n".join(
        [f"- {m['name']} — {m['position']}: {m.get('bio', 'Nije navedena biografija')}" 
         for m in filtered_data.get('teamMembers', [])]
    )
    portfolio = "\n".join(
        [f"- {p['project-name']}: {p.get('project-description', 'Nije naveden opis')}" 
         for p in filtered_data.get('portfolio', [])]
    )
    social_media = "\n".join(
        [f"{key.capitalize()}: {value}" for key, value in {
            'facebook': filtered_data.get('facebook', ''),
            'twitter': filtered_data.get('twitter', ''),
            'instagram': filtered_data.get('instagram', ''),
            'linkedin': filtered_data.get('linkedin', '')
        }.items() if value]
    )

    prompt = f"""
Napravi modernu i profesionalnu veb stranicu za sledeću firmu:

Naziv firme: {filtered_data.get('companyName', 'Nije navedeno')}
Slogan: {filtered_data.get('slogan', 'Nije navedeno')}
Opis: {filtered_data.get('companyDescription', 'Nije navedeno')}
Delatnost: {filtered_data.get('industry', 'Nije navedeno')}
Godina osnivanja: {filtered_data.get('yearFounded', 'Nije navedeno')}
Broj zaposlenih: {filtered_data.get('employees', 'Nije navedeno')}
Kontakt:
- Email: {filtered_data.get('email', 'Nije navedeno')}
- Telefon: {filtered_data.get('phone', 'Nije navedeno')}
- Adresa: {filtered_data.get('address', 'Nije navedena')}
Društvene mreže:
{social_media if social_media else 'Nije navedeno'}
Radno vreme: {filtered_data.get('working-hours', 'Nije navedeno')}
Lokacija na mapi: {filtered_data.get('map-embed', 'Nije navedeno')}

Usluge/Proizvodi:
{services if services else 'Nije navedeno'}

Portfolio:
{portfolio if portfolio else 'Nije navedeno'}

Tim:
{team if team else 'Nije navedeno'}

Kultura firme: {filtered_data.get('culture', 'Nije navedeno')}

Vizuelni identitet:
- Logo: {filtered_data.get('logo', 'Nije navedeno')}
- Glavna boja: {filtered_data.get('primaryColor', 'Nije navedeno')}
- Sekundarna boja: {filtered_data.get('secondaryColor', 'Nije navedeno')}
- Stil dizajna: {filtered_data.get('style', 'Nije navedeno')}
- Font: {filtered_data.get('font', 'Nije navedeno')}
- Dodatne slike: {', '.join(filtered_data.get('images', [])) if filtered_data.get('images') else 'Nije navedeno'}

Stranice sajta: {', '.join(filtered_data.get('pages', [])) if filtered_data.get('pages') else 'Nije navedeno'}
Jezik sajta: {filtered_data.get('language', 'Nije navedeno')}
Registracija domena: {filtered_data.get('hasDomain', 'Ne')} ({filtered_data.get('domain', 'Nije navedeno')})
Hosting: {filtered_data.get('hasHosting', 'Ne')}
Dodatne napomene: {filtered_data.get('notes', 'Nije navedeno')}
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

        # Snimi prompt kao .txt fajl
        prompt_file = save_prompt_to_txt(data['companyName'], prompt)

        # Kreiraj URL za preuzimanje fajla
        prompt_url = f"https://stranicax.onrender.com/download-prompt/{data['companyName'].lower().replace(' ', '-')}-prompt.txt"

        return jsonify({"status": "success", "prompt": prompt, "prompt_file": prompt_file, "prompt_url": prompt_url})
    except ValueError as e:
        print("Greška:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        print("Neočekivana greška:", str(e))
        return jsonify({"status": "error", "message": "Neočekivana greška na serveru"}), 500

@app.route('/download-prompt/<filename>', methods=['GET'])
def download_prompt(filename):
    try:
        return send_from_directory(PROMPT_DIR, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Fajl nije pronađen"}), 404

if __name__ == '__main__':
    app.run(debug=True)
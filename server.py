from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # ✅ dozvoljava zahtjeve sa drugih domena

@app.route('/submit-form', methods=['POST'])
def receive_form():
    data = request.json
    print("Primljeni podaci:", data)
    return jsonify({"status": "success", "received": data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

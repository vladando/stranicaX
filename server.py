# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/submit-form', methods=['POST'])
def receive_form():
    data = request.json  # Ako šalješ JSON sa formulara
    print("Primljeni podaci:", data)
    return jsonify({"status": "success", "received": data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

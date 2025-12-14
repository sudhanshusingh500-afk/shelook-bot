import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        # 1. Check if Keys exist
        if not GROQ_API_KEY: return jsonify({"reply": "DEBUG ERROR: GROQ_API_KEY is missing in Render."})
        if not SHOPIFY_URL: return jsonify({"reply": "DEBUG ERROR: SHOPIFY_STORE_URL is missing."})

        msg = data.get('message')
        
        # 2. Try to talk to Groq
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": msg}],
            model="llama3-70b-8192"
        )
        return jsonify({"reply": completion.choices[0].message.content})

    except Exception as e:
        # This will show the REAL error in your chat window
        return jsonify({"reply": f"REAL ERROR: {str(e)}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

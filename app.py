import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app) 

# --- CONFIGURATION ---
API_KEY = os.environ.get("GOOGLE_API_KEY")

# We use the direct URL for Gemini 1.5 Flash
# This bypasses library version issues
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"

SYSTEM_INSTRUCTION = """
You are the helpful, polite, and elegant customer support AI for 'SHELOOK', a premium silver jewelry brand.
Your goal is to answer customer questions concisely based STRICTLY on the policies below.

--- COMPANY DETAILS ---
Brand: SHELOOK (owned by Optical Line).
Location: Chandannagar, West Bengal, India.
Contact: +91-74392-28282 | support@shelook.in

--- KEY POLICIES ---
1. SHIPPING:
   - Free shipping on orders above ₹1999.
   - Flat ₹70 fee for orders below ₹1999.
   - Standard Delivery: 5–7 business days. Express: 2–3 days (+₹100).
   - Ships within India only.

2. RETURNS & EXCHANGES:
   - Window: Accepted within 14 DAYS of purchase/delivery.
   - Condition: Must be unused, undamaged, and with original tags intact.
   - Process: Subject to Quality Check (QC).
   
3. REFUNDS (Online Orders):
   - Processed within 7–10 working days AFTER Quality Check approval.
   - Credited back to the original payment method.
   - COD Orders: Refunded via Bank Transfer or Store Credit.

4. WARRANTY & CARE:
   - 6-Month Warranty on manufacturing defects (loose stones, broken clasps).
   - Free 3-Year Plating Service (1 service per year). Courier charges apply.

5. ORDER STATUS:
   - If a user asks "Where is my order?", politely ask for their "Order ID" and "Email Address".

--- TONE ---
- Be warm and professional.
- Keep answers short (2-3 sentences).
"""

def get_ai_response(user_message):
    if not API_KEY:
        return "Error: Server API Key is missing."

    # Construct the JSON payload for Google
    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_INSTRUCTION}\n\nUSER QUESTION: {user_message}"}]
        }]
    }

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        
        # Check if Google accepted it
        if response.status_code == 200:
            data = response.json()
            # Extract the text answer
            # We add a safety check here in case Google returns an empty answer
            try:
                return data['candidates'][0]['content']['parts'][0]['text']
            except (KeyError, IndexError):
                return "I'm having a bit of trouble thinking right now. Please try again."
        else:
            return f"Error from Google: {response.status_code} - {response.text}"
            
    except Exception as e:
        return f"Connection Error: {str(e)}"

@app.route('/', methods=['GET'])
def home():
    return "SHELOOK AI Bot is Running (Direct Mode)!"

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message', '')
    if not user_message:
        return jsonify({"reply": "Please say something!"})

    ai_reply = get_ai_response(user_message)
    return jsonify({"reply": ai_reply})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app) 

# Setup Logging so we can see errors in Render Dashboard
logging.basicConfig(level=logging.INFO)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

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
    # List of models to try in order. One of these WILL work.
    models_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-flash-latest',
        'gemini-pro',
        'gemini-1.0-pro'
    ]
    
    last_error = ""

    for model_name in models_to_try:
        try:
            print(f"Trying model: {model_name}...")
            model = genai.GenerativeModel(model_name)
            prompt = f"{SYSTEM_INSTRUCTION}\n\nUSER QUESTION: {user_message}"
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            last_error = str(e)
            print(f"Model {model_name} failed: {e}")
            continue # Try the next model in the list

    # If all fail, return the error
    return f"I apologize, I am having connection issues. (Debug: {last_error})"

@app.route('/', methods=['GET'])
def home():
    return "SHELOOK AI Bot is Running!"

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

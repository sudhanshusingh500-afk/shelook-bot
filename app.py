import os
import re
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

# 1. SETUP
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

# 2. HELPER: Extractions (The Safety Net)
def extract_details(text):
    """Finds Email and Order ID in text even if Frontend missed them."""
    email = None
    order_id = None
    
    # Search for Email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    if email_match:
        email = email_match.group(0)
        
    # Search for Order ID (SL followed by numbers)
    order_match = re.search(r'(SL\d+)', text, re.IGNORECASE)
    if order_match:
        order_id = order_match.group(1).upper()
        
    return email, order_id

# 3. SHOPIFY TOOLS
def get_shopify_order(order_id):
    # Remove any spaces just in case
    clean_id = order_id.replace(" ", "")
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={clean_id}&status=any"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        if not data.get('orders'): return None
        return data['orders'][0]
    except: return None

def check_status(order_id):
    order = get_shopify_order(order_id)
    if not order: return f"I looked for Order {order_id} but couldn't find it in our system. Please check the number."
    
    status = order.get('fulfillment_status') or "Unfulfilled"
    tracking = "No tracking info yet."
    if order.get('fulfillments'):
        t = order['fulfillments'][0]
        tracking = t.get('tracking_url') or f"Tracking Number: {t.get('tracking_number')}"
    
    return f"📦 **Order {order['name']}**\n- Status: {status}\n- {tracking}"

def cancel_order(order_id):
    order = get_shopify_order(order_id)
    if not order: return "Order not found."
    if order.get('fulfillment_status') == 'fulfilled':
        return "⚠️ Failed: Order already shipped. Cannot cancel."
    
    try:
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders/{order['id']}/cancel.json"
        requests.post(url, headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN}, json={})
        return "✅ Success: Order cancelled and refund processed."
    except: return "❌ Technical error while cancelling."

# 4. CHAT ROUTE
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    msg = data.get('message', '')
    
    # A. Get Context from Frontend OR Text
    email_in_payload = data.get('email')
    order_in_payload = data.get('orderId')
    
    # B. Run Backup Extraction (If frontend sent nothing, maybe text has it)
    extracted_email, extracted_order = extract_details(msg)
    
    # C. Finalize Variables
    email = email_in_payload or extracted_email
    order_id = order_in_payload or extracted_order

    # D. Strict System Prompt
    system_prompt = f"""
    You are the SHELOOK Jewelry Support Bot.
    
    STRICT RULES:
    1. NEVER say "I am a large language model".
    2. If user asks about Order Status/Tracking/Cancel:
       - CHECK: Do I have the Order ID? (Current value: {order_id})
       - IF Missing ID: Ask "Please provide your Order ID (starts with SL)."
       - IF Have ID: IMMEDIATEY use the tool 'check_status' or 'cancel_order'.
    3. General questions (silver care, styling): Answer politely.
    
    Current User Email: {email}
    Current Order ID: {order_id}
    """

    tools = [
        {"type": "function", "function": {"name": "check_status", "description": "Get status", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "cancel_order", "description": "Cancel order", "parameters": {"type": "object", "properties": {}}}}
    ]

    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": msg}],
            model="llama-3.3-70b-versatile", # <--- NEW MODEL
            tools=tools,
            tool_choice="auto"
        )
        
        reply = completion.choices[0].message.content
        tool_calls = completion.choices[0].message.tool_calls

        if tool_calls:
            if not order_id: 
                reply = "I can check that for you, but I need your Order ID (e.g., SL1001) first."
            else:
                fn = tool_calls[0].function.name
                if fn == "check_status": reply = check_status(order_id)
                if fn == "cancel_order": reply = cancel_order(order_id)

        return jsonify({
            "reply": reply,
            # We send these back so the Frontend can remember them!
            "found_email": email, 
            "found_orderId": order_id
        })
        
    except Exception as e:
        return jsonify({"reply": f"System Error: {str(e)}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

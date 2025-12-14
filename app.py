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
    if not order: return f"I looked for Order {order_id} but couldn't find it. Please double-check the ID."
    
    status = order.get('fulfillment_status') or "Unfulfilled (Processing)"
    financial = order.get('financial_status')
    
    tracking_msg = "No tracking info yet."
    if order.get('fulfillments'):
        t = order['fulfillments'][0]
        if t.get('tracking_url'):
            tracking_msg = f"Tracking Link: {t.get('tracking_url')}"
        elif t.get('tracking_number'):
            tracking_msg = f"Tracking Number: {t.get('tracking_number')}"
    
    return f"📦 **Order {order['name']}**\n- Status: {status}\n- Payment: {financial}\n- {tracking_msg}"

def cancel_order(order_id):
    order = get_shopify_order(order_id)
    if not order: return "Order not found."
    
    # POLICY: Cannot cancel if shipped
    if order.get('fulfillment_status') == 'fulfilled':
        return "⚠️ **Cancellation Failed:**\nYour order has already been shipped. We cannot cancel it now. Please reach out to us for a return after delivery: support@shelook.com"
    
    try:
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders/{order['id']}/cancel.json"
        requests.post(url, headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN}, json={})
        return "✅ **Success:** Your order has been cancelled and a refund is being processed."
    except: return "❌ Technical error. Please contact support@shelook.com."

# 4. CHAT ROUTE
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    msg = data.get('message', '')
    
    # Context Logic
    email_in_payload = data.get('email')
    order_in_payload = data.get('orderId')
    extracted_email, extracted_order = extract_details(msg)
    
    email = email_in_payload or extracted_email
    order_id = order_in_payload or extracted_order

    # SYSTEM PROMPT (The Personality)
    system_prompt = f"""
    You are the SHELOOK Jewelry Support Assistant.
    
    **YOUR RULES:**
    1. **Strict Tasks:** If the user asks for Status, Tracking, or Cancel:
       - CHECK: Do you have the Order ID? (Current: {order_id})
       - IF YES -> Call tool 'check_status' or 'cancel_order' IMMEDIATELY.
       - IF NO -> Ask: "Please provide your Order ID (starts with SL)."
    
    2. **General Qs:** Answer questions about silver, jewelry care, and style briefly and politely.
    
    3. **Unknowns:** If you are NOT sure about an answer (e.g., specific manufacturing details, complex return cases), do NOT guess.
       - SAY EXACTLY: "I'm not sure about that, but our team can help! Please contact us at **support@shelook.com**."
       
    4. **Identity:** Never say "I am a language model". Say "I am the SHELOOK Assistant".

    Current User Email: {email}
    Current Order ID: {order_id}
    """

    tools = [
        {"type": "function", "function": {"name": "check_status", "description": "Get status/tracking", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "cancel_order", "description": "Cancel order", "parameters": {"type": "object", "properties": {}}}}
    ]

    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": msg}],
            model="llama-3.3-70b-versatile",
            tools=tools,
            tool_choice="auto"
        )
        
        reply = completion.choices[0].message.content
        tool_calls = completion.choices[0].message.tool_calls

        if tool_calls:
            if not order_id: 
                reply = "I can help with that, but I need your Order ID (e.g., SL1001) first."
            else:
                fn = tool_calls[0].function.name
                if fn == "check_status": reply = check_status(order_id)
                if fn == "cancel_order": reply = cancel_order(order_id)

        return jsonify({
            "reply": reply,
            "found_email": email, 
            "found_orderId": order_id
        })
        
    except Exception as e:
        return jsonify({"reply": "I'm having a brief technical moment. Please try again or email support@shelook.com."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

import os
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

# 2. SHOPIFY TOOLS (HANDS)
def get_shopify_order(order_id):
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={order_id}&status=any"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        if not data.get('orders'): return None
        return data['orders'][0]
    except: return None

def check_status(order_id):
    order = get_shopify_order(order_id)
    if not order: return "Order not found. Check ID."
    
    status = order.get('fulfillment_status') or "Unfulfilled"
    tracking = "No tracking yet"
    if order.get('fulfillments'):
        t = order['fulfillments'][0]
        tracking = t.get('tracking_url') or t.get('tracking_number')
    
    return f"📦 Status: {status}\nTracking: {tracking}"

def cancel_order(order_id):
    order = get_shopify_order(order_id)
    if not order: return "Order not found."
    if order.get('fulfillment_status') == 'fulfilled':
        return "⚠️ Cannot cancel: Order already shipped."
    
    try:
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders/{order['id']}/cancel.json"
        requests.post(url, headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN}, json={})
        return "✅ Success: Order cancelled."
    except: return "❌ Error cancelling order."

# 3. CHAT ROUTE (BRAIN)
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    msg = data.get('message')
    email = data.get('email')
    order_id = data.get('orderId')

    system_prompt = f"""
    You are SHELOOK Support.
    1. General Qs: Answer briefly and friendly.
    2. Tasks (Status/Cancel): MUST have Email & Order ID.
       - If missing -> Ask user.
       - If present -> Use tool 'check_status' or 'cancel_order'.
    User Context: Email={email}, ID={order_id}
    """

    tools = [
        {"type": "function", "function": {"name": "check_status", "description": "Check status", "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "cancel_order", "description": "Cancel order", "parameters": {"type": "object", "properties": {}}}}
    ]

    try:
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": msg}],
            model="llama3-70b-8192",
            tools=tools,
            tool_choice="auto"
        )
        
        reply = completion.choices[0].message.content
        tool_calls = completion.choices[0].message.tool_calls

        if tool_calls:
            if not order_id: reply = "Please provide your Order ID first."
            else:
                fn = tool_calls[0].function.name
                if fn == "check_status": reply = check_status(order_id)
                if fn == "cancel_order": reply = cancel_order(order_id)

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"reply": "System Error. Please try again."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

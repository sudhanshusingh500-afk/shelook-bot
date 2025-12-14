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

# 2. HELPER: Extractions
def extract_details(text):
    """Finds Email and Order ID in text."""
    email = None
    order_id = None
    
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    if email_match:
        email = email_match.group(0)
        
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

def find_product_link(query):
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/products.json?title={query}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    try:
        response = requests.get(url, headers=headers)
        products = response.json().get('products', [])
        if not products: return "I couldn't find a product with that name."
        product = products[0]
        # Change .in to .com if needed
        product_url = f"https://{SHOPIFY_URL.replace('.myshopify.com', '.in')}/products/{product['handle']}"
        return f"I don't have the exact details here, but you can view the full specifications on our website: {product_url}"
    except: return "I couldn't retrieve the link right now."

def check_status(order_id, user_email):
    order = get_shopify_order(order_id)
    if not order: return f"I looked for Order {order_id} but couldn't find it."
    
    # SECURITY CHECK
    if not user_email or order['email'].lower().strip() != user_email.lower().strip():
        return "⚠️ **Verification Failed:** The email provided does not match this order. Please reach out to **support@shelook.com**."
    
    status = order.get('fulfillment_status') or "Unfulfilled (Processing)"
    tracking_msg = "No tracking info yet."
    if order.get('fulfillments'):
        t = order['fulfillments'][0]
        if t.get('tracking_url'): tracking_msg = f"Tracking Link: {t.get('tracking_url')}"
        elif t.get('tracking_number'): tracking_msg = f"Tracking Number: {t.get('tracking_number')}"
    
    return f"📦 **Order {order['name']}**\n- Status: {status}\n- {tracking_msg}"

def cancel_order(order_id, user_email):
    order = get_shopify_order(order_id)
    if not order: return "Order not found."

    if not user_email or order['email'].lower().strip() != user_email.lower().strip():
         return "⚠️ **Verification Failed:** The email does not match. Please contact **support@shelook.com**."
    
    if order.get('fulfillment_status') == 'fulfilled':
        return "⚠️ **Cancellation Failed:** Order already shipped. Please contact support@shelook.com."
    
    try:
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders/{order['id']}/cancel.json"
        requests.post(url, headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN}, json={})
        return "✅ **Success:** Order cancelled."
    except: return "❌ Technical error."

# 4. CHAT ROUTE
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    msg = data.get('message', '')
    
    email_in_payload = data.get('email')
    order_in_payload = data.get('orderId')
    extracted_email, extracted_order = extract_details(msg)
    
    email = email_in_payload or extracted_email
    order_id = order_in_payload or extracted_order

    # --- UPDATED SYSTEM PROMPT (THE LOGIC CHANGE) ---
    system_prompt = f"""
    You are the SHELOOK Jewelry Assistant.
    
    RULES:
    1. **Order Tasks (Status/Tracking/Cancel):**
       - **STEP 1:** Check if you have the **Order ID** (Current: {order_id}).
         - If NO -> Ask: "Please provide your Order ID first (e.g., SL1001)." (STOP HERE).
       
       - **STEP 2:** If you have Order ID, Check if you have the **Email** (Current: {email}).
         - If NO -> Ask: "Thanks. Now please provide the Email Address for verification." (STOP HERE).
         
       - **STEP 3:** If you have BOTH -> Call tool 'check_status' or 'cancel_order'.

    2. **Product Questions:** Use 'find_product_link' for specifics (grams, etc).
    3. **Unknowns:** If unsure, say "Please contact support@shelook.com".
    4. **Identity:** Never say "I am a language model".

    Current Email: {email}
    Current Order ID: {order_id}
    """

    tools = [
        {"type": "function", "function": {"name": "check_status", "description": "Check status", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}},
        {"type": "function", "function": {"name": "cancel_order", "description": "Cancel order", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}},
        {"type": "function", "function": {"name": "find_product_link", "description": "Find product link", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
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
            fn = tool_calls[0].function.name
            args = json.loads(tool_calls[0].function.arguments)
            
            if fn == "find_product_link":
                reply = find_product_link(args.get('query'))
            elif fn == "check_status":
                # Double check logic (Redundant but safe)
                if not order_id: reply = "Please provide your Order ID first."
                elif not email: reply = "Please confirm your Email Address."
                else: reply = check_status(order_id, args.get('user_email', email))
            elif fn == "cancel_order":
                if not order_id: reply = "Please provide your Order ID first."
                elif not email: reply = "Please confirm your Email Address."
                else: reply = cancel_order(order_id, args.get('user_email', email))

        return jsonify({
            "reply": reply,
            "found_email": email, 
            "found_orderId": order_id
        })
        
    except Exception as e:
        return jsonify({"reply": "I'm having a brief technical moment. Please try again."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

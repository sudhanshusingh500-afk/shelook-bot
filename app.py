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

# 3. SHOPIFY TOOLS (HANDS)

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

# NEW TOOL: Search Product Link
def find_product_link(query):
    """Searches Shopify for a product and returns the link."""
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/products.json?title={query}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    try:
        response = requests.get(url, headers=headers)
        products = response.json().get('products', [])
        
        if not products:
            return "I couldn't find a product with that name on our website."
            
        # Get the best match
        product = products[0]
        # Construct the live URL (assuming standard Shopify structure)
        product_url = f"https://{SHOPIFY_URL.replace('.myshopify.com', '.in')}/products/{product['handle']}"
        # Note: If your domain is .com, change .in to .com above
        
        return f"I don't have the exact specification right here, but you can check the full details on the product page: {product_url}"
    except:
        return "I couldn't retrieve the product link at the moment."

def check_status(order_id, user_email):
    order = get_shopify_order(order_id)
    if not order: return f"I looked for Order {order_id} but couldn't find it."
    
    # SECURITY CHECK
    if not user_email or order['email'].lower().strip() != user_email.lower().strip():
        return "⚠️ **Security Alert:** The email you provided does not match the order records. For privacy, please contact our team at **support@shelook.com**."
    
    status = order.get('fulfillment_status') or "Unfulfilled (Processing)"
    tracking_msg = "No tracking info yet."
    if order.get('fulfillments'):
        t = order['fulfillments'][0]
        if t.get('tracking_url'):
            tracking_msg = f"Tracking Link: {t.get('tracking_url')}"
        elif t.get('tracking_number'):
            tracking_msg = f"Tracking Number: {t.get('tracking_number')}"
    
    return f"📦 **Order {order['name']}**\n- Status: {status}\n- {tracking_msg}"

def cancel_order(order_id, user_email):
    order = get_shopify_order(order_id)
    if not order: return "Order not found."

    # SECURITY CHECK
    if not user_email or order['email'].lower().strip() != user_email.lower().strip():
         return "⚠️ **Verification Failed:** The email address does not match this order. Please reach out to **support@shelook.com** for assistance."
    
    # POLICY CHECK
    if order.get('fulfillment_status') == 'fulfilled':
        return "⚠️ **Cancellation Failed:** Order already shipped. Please contact support@shelook.com for a return."
    
    try:
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders/{order['id']}/cancel.json"
        requests.post(url, headers={"X-Shopify-Access-Token": SHOPIFY_TOKEN}, json={})
        return "✅ **Success:** Your order has been cancelled."
    except: return "❌ Technical error. Please contact support@shelook.com."

# 4. CHAT ROUTE (THE BRAIN)
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

    # SYSTEM PROMPT
    system_prompt = f"""
    You are the SHELOOK Jewelry Assistant.
    
    RULES:
    1. **Product Questions:** If user asks for specific details (grams, weight, stone type) that you don't know:
       - Use the tool 'find_product_link' to search for the item.
       - Do NOT guess.
       
    2. **Order Tasks (Status/Cancel):** - You MUST have **Email** AND **Order ID**.
       - If missing, ask for them.
       - If you have them, call 'check_status' or 'cancel_order' AND pass the email for verification.
       
    3. **General:** Be polite and helpful. NEVER say "I am a language model".
    
    Current Email: {email}
    Current Order ID: {order_id}
    """

    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_status",
                "description": "Check status with email verification",
                "parameters": {
                    "type": "object",
                    "properties": {
                        # We force the AI to pass the email it found in context
                        "user_email": {"type": "string", "description": "The user's email address for verification"} 
                    },
                    "required": ["user_email"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_order",
                "description": "Cancel order with email verification",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_email": {"type": "string", "description": "The user's email address for verification"}
                    },
                    "required": ["user_email"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_product_link",
                "description": "Find a product link when user asks for specific details",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The name of the product (e.g. Peacock Ring)"}
                    },
                    "required": ["query"]
                }
            }
        }
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
                if not order_id: reply = "Please provide your Order ID first."
                else: reply = check_status(order_id, args.get('user_email', email))
                
            elif fn == "cancel_order":
                if not order_id: reply = "Please provide your Order ID first."
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

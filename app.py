import os
import re
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

# 1. CONFIGURATION
# Render uses these to connect
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL") # This should be: 1bp4n0-zv.myshopify.com
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

# YOUR PUBLIC DOMAIN (Hardcoded to fix the link issue)
PUBLIC_DOMAIN = "shelook.in"

client = Groq(api_key=GROQ_API_KEY)

# 2. HELPER FUNCTIONS
def extract_details(text):
    email = None
    order_id = None
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    if email_match: email = email_match.group(0)
    order_match = re.search(r'(SL\d+)', text, re.IGNORECASE)
    if order_match: order_id = order_match.group(1).upper()
    return email, order_id

def get_shopify_headers():
    return {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

# 3. TOOLS

def find_product_link(query):
    # Search Shopify for the product
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/products.json?title={query}"
    try:
        response = requests.get(url, headers=get_shopify_headers())
        data = response.json()
        products = data.get('products', [])
        
        # If no exact match, return a General Search Link
        if not products:
            search_url = f"https://{PUBLIC_DOMAIN}/search?q={query}"
            # Returns a clickable HTML link
            return f"I couldn't find an exact match, but you can browse our <b>{query} collection</b> here: <br><a href='{search_url}' target='_blank' style='color:blue; text-decoration:underline;'>View {query} Collection</a>"
            
        # If product found, create a direct link
        product = products[0]
        product_url = f"https://{PUBLIC_DOMAIN}/products/{product['handle']}"
        
        # Returns a nice clickable HTML link
        return f"I recommend our <b>{product['title']}</b>. <br><br>👉 <a href='{product_url}' target='_blank' style='background:#000; color:#fff; padding:5px 10px; border-radius:15px; text-decoration:none;'>View Product</a>"
    except Exception as e:
        print(f"Search Error: {e}")
        return "I'm having trouble searching our catalog right now."

def check_status(order_id, user_email):
    clean_id = order_id.replace(" ", "")
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={clean_id}&status=any"
    try:
        response = requests.get(url, headers=get_shopify_headers())
        data = response.json()
        if not data.get('orders'): return f"I couldn't find Order {order_id}. Please check the number."
            
        order = data['orders'][0]
        
        # Email Validation
        order_email = order.get('email') or ""
        customer_email = order.get('customer', {}).get('email') or ""
        
        if user_email.lower().strip() not in [order_email.lower(), customer_email.lower()]:
             return "⚠️ **Security Alert:** The email provided does not match this order. Please contact support@shelook.com."

        status = order.get('fulfillment_status') or "Unfulfilled"
        tracking = "No tracking info yet."
        if order.get('fulfillments'):
            t = order['fulfillments'][0]
            if t.get('tracking_url'):
                tracking = f"<a href='{t.get('tracking_url')}' target='_blank'>Track Shipment</a>"
            else:
                tracking = t.get('tracking_number') or "Shipped"
        
        return f"📦 **Order {order['name']}**<br>Status: {status}<br>Tracking: {tracking}"
    except: return "System error checking status."

def cancel_order(order_id, user_email):
     return "To cancel your order, please email us directly at <a href='mailto:support@shelook.com'>support@shelook.com</a> for immediate assistance."

# 4. CHAT ROUTE
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        msg = data.get('message', '')
        
        email = data.get('email') or extract_details(msg)[0]
        order_id = data.get('orderId') or extract_details(msg)[1]

        # SYSTEM PROMPT
        system_prompt = f"""
        You are the SHELOOK Jewelry Assistant.
        
        RULES:
        1. **Product Recommendations:** - If the user asks for a product (e.g., "anklet", "ring"), ALWAYS use the 'find_product_link' tool.
           - Do NOT provide a text URL yourself. Let the tool generate the clickable link.
           
        2. **Order Status:** - User needs Order ID AND Email.
           - If missing, ask for them politely.
           
        3. **Style:** Keep answers short. Use HTML for formatting if needed.

        Context: Email={email}, OrderID={order_id}
        """

        tools = [
            {"type": "function", "function": {"name": "check_status", "description": "Check status", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}},
            {"type": "function", "function": {"name": "find_product_link", "description": "Search product and return clickable link", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
        ]

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
                elif not email: reply = "Please confirm your Email Address."
                else: reply = check_status(order_id, args.get('user_email', email))

        return jsonify({"reply": reply, "found_email": email, "found_orderId": order_id})
        
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        return jsonify({"reply": "I'm having a brief technical moment. Please try again."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

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
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

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
    # Searches Shopify for a product to recommend
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/products.json?title={query}"
    try:
        response = requests.get(url, headers=get_shopify_headers())
        products = response.json().get('products', [])
        
        if not products:
            # Fallback: Link to the search page if specific product not found
            search_url = f"https://{SHOPIFY_URL.replace('.myshopify.com', '.in')}/search?q={query}"
            return f"I think you'd love our **{query}** collection! Check them out here: {search_url}"
            
        # Get the best match
        product = products[0]
        base_domain = SHOPIFY_URL.replace('.myshopify.com', '.in')
        product_url = f"https://{base_domain}/products/{product['handle']}"
        
        return f"I recommend checking out our **{product['title']}**. It's a perfect match! View it here: {product_url}"
    except:
        return ""

def check_status(order_id, user_email):
    clean_id = order_id.replace(" ", "")
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={clean_id}&status=any"
    try:
        response = requests.get(url, headers=get_shopify_headers())
        data = response.json()
        if not data.get('orders'): return f"I couldn't find Order {order_id}."
            
        order = data['orders'][0]
        
        # Email Validation
        order_email = order.get('email') or ""
        customer_email = order.get('customer', {}).get('email') or ""
        
        if user_email.lower().strip() not in [order_email.lower(), customer_email.lower()]:
             return "⚠️ **Security Alert:** Email mismatch. Please contact support@shelook.com."

        status = order.get('fulfillment_status') or "Unfulfilled"
        tracking = "No tracking info yet."
        if order.get('fulfillments'):
            t = order['fulfillments'][0]
            tracking = t.get('tracking_url') or t.get('tracking_number') or "Shipped"
        
        return f"📦 **Order {order['name']}**\n- Status: {status}\n- Tracking: {tracking}"
    except: return "System error checking status."

def cancel_order(order_id, user_email):
    # Same logic as before
    return "Please contact support to cancel for now." # Simplified for brevity, you can paste full logic if needed

# 4. CHAT ROUTE
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        msg = data.get('message', '')
        
        email = data.get('email') or extract_details(msg)[0]
        order_id = data.get('orderId') or extract_details(msg)[1]

        # SYSTEM PROMPT (UPDATED FOR SALES)
        system_prompt = f"""
        You are the SHELOOK Jewelry Assistant.
        
        RULES:
        1. **Order Tasks:** - IF NO Order ID -> Ask for Order ID.
           - IF NO Email -> Ask for Email.
           - IF BOTH -> Use 'check_status'.
           
        2. **Recommendations (SALES MODE):** - If you suggest a jewelry type (e.g. "Try Oxidized Earrings"), you MUST use 'find_product_link' to find it in our store.
           - NEVER suggest generic items without a link. Always try to close the sale.
           
        3. **Product Details:** Use 'find_product_link' for specs (grams, stone).
        
        4. **General:** Be brief and helpful. No "I am an AI".

        Context: Email={email}, OrderID={order_id}
        """

        tools = [
            {"type": "function", "function": {"name": "check_status", "description": "Check status", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}},
            {"type": "function", "function": {"name": "find_product_link", "description": "Find product link for recommendation or specs", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
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
        return jsonify({"reply": "I'm having a brief technical moment. Please try again."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

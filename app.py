# ==========================================
# BLOCK 1: CONFIGURATION & SETUP
# ==========================================
import os
import re
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)

# Environment Variables
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL")
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")
PUBLIC_DOMAIN = "shelook.in"

# Initialize AI
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# BLOCK 2: SHOPIFY API CLIENT (The Hands)
# ==========================================
class ShopifyClient:
    """Handles all raw communication with Shopify."""
    
    @staticmethod
    def get_headers():
        return {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

    @staticmethod
    def search_product(query):
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/products.json?title={query}"
        try:
            return requests.get(url, headers=ShopifyClient.get_headers()).json().get('products', [])
        except: return []

    @staticmethod
    def get_order(order_id):
        clean_id = order_id.replace(" ", "")
        url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={clean_id}&status=any"
        try:
            data = requests.get(url, headers=ShopifyClient.get_headers()).json()
            return data.get('orders', [])[0] if data.get('orders') else None
        except: return None

# ==========================================
# BLOCK 3: SECURITY & BUSINESS LOGIC (The Brain)
# ==========================================
class BusinessLogic:
    """Decides what is allowed and formats answers."""

    @staticmethod
    def verify_user(order, user_email, action_type):
        """
        Returns True if access allowed, False otherwise.
        - Status Check: Allow if emails match OR if Shopify data is missing (Test Mode).
        - Cancellation: STRICT. Must match exactly. No Bypass.
        """
        if not order: return False
        
        # 1. Gather all emails on file
        shopify_emails = []
        if order.get('email'): shopify_emails.append(order.get('email').lower().strip())
        if order.get('contact_email'): shopify_emails.append(order.get('contact_email').lower().strip())
        if order.get('customer') and order['customer'].get('email'):
            shopify_emails.append(order['customer']['email'].lower().strip())
            
        input_email = user_email.lower().strip()
        
        # 2. STRICT CHECK (For Cancellation)
        if action_type == "cancel":
            if input_email in shopify_emails:
                return True
            return False # Fail if no match, even if shopify_emails is empty

        # 3. LENIENT CHECK (For Status/Tracking)
        if action_type == "status":
            if not shopify_emails: 
                return True # Bypass if Shopify has no data (Test Order)
            if input_email in shopify_emails:
                return True
            return False

        return False

    @staticmethod
    def format_product_link(query, products):
        if not products:
            search_url = f"https://{PUBLIC_DOMAIN}/search?q={query}"
            return f"I couldn't find an exact match, but you can browse our collection here: <br><a href='{search_url}' target='_blank' style='color:blue;'>View {query} Collection</a>"
            
        p = products[0]
        url = f"https://{PUBLIC_DOMAIN}/products/{p['handle']}"
        img = p['image']['src'] if p.get('image') else ""
        
        html = f"I recommend our <b>{p['title']}</b>.<br>"
        if img: html += f"<img src='{img}' style='width:100%; border-radius:8px; margin:10px 0;'><br>"
        html += f"👉 <a href='{url}' target='_blank' style='background:#000; color:#fff; padding:8px 15px; border-radius:20px; text-decoration:none;'>View Product</a>"
        return html

    @staticmethod
    def format_status(order):
        status = order.get('fulfillment_status') or "Unfulfilled"
        financial = order.get('financial_status') or "Pending"
        track_link = "Processing"
        
        if order.get('fulfillments'):
            t = order['fulfillments'][0]
            if t.get('tracking_url'):
                track_link = f"<a href='{t.get('tracking_url')}' target='_blank'>Track Shipment</a>"
            else:
                track_link = t.get('tracking_number') or "Shipped"
                
        return f"📦 **Order {order['name']}**<br>Payment: {financial}<br>Status: {status}<br>Tracking: {track_link}"

# ==========================================
# BLOCK 4: MAIN APP ROUTE
# ==========================================
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        msg = data.get('message', '')
        
        # 1. Extract Details
        extracted_email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', msg)
        email = data.get('email') or (extracted_email.group(0) if extracted_email else None)
        
        extracted_order = re.search(r'(SL\s*\d+)', msg, re.IGNORECASE)
        order_id = data.get('orderId') or (extracted_order.group(1).upper().replace(" ", "") if extracted_order else None)

        # 2. Define Tools
        tools = [
            {"type": "function", "function": {"name": "check_status", "description": "Check status", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}},
            {"type": "function", "function": {"name": "find_product", "description": "Search product", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "cancel_order", "description": "Cancel order", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}}
        ]

        # 3. System Prompt
        system_prompt = f"""
        You are the SHELOOK Jewelry Assistant.
        
        RULES:
        1. **Flow:** Ask for Order ID first. Wait. Then ask for Email. Wait.
        2. **Status/Cancel:** Use tools 'check_status' or 'cancel_order' only when you have BOTH.
        3. **Products:** Use 'find_product'.

        Context: Email={email}, OrderID={order_id}
        """

        # 4. AI Call
        completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": msg}],
            model="llama-3.3-70b-versatile",
            tools=tools,
            tool_choice="auto"
        )
        
        reply = completion.choices[0].message.content
        tool_calls = completion.choices[0].message.tool_calls

        # 5. Tool Execution Logic
        if tool_calls:
            fn = tool_calls[0].function.name
            args = json.loads(tool_calls[0].function.arguments)
            
            if fn == "find_product":
                prods = ShopifyClient.search_product(args.get('query'))
                reply = BusinessLogic.format_product_link(args.get('query'), prods)
            
            elif fn == "check_status":
                if not order_id: reply = "Please provide your Order ID first."
                elif not email: reply = "Please provide your Email Address."
                else:
                    order = ShopifyClient.get_order(order_id)
                    if not order: reply = "Order not found."
                    else:
                        # LENIENT CHECK
                        is_allowed = BusinessLogic.verify_user(order, args.get('user_email', email), "status")
                        if is_allowed: reply = BusinessLogic.format_status(order)
                        else: reply = "⚠️ Verification Failed. Email mismatch."

            elif fn == "cancel_order":
                if not order_id: reply = "Please provide your Order ID first."
                elif not email: reply = "Please provide your Email Address."
                else:
                    order = ShopifyClient.get_order(order_id)
                    if not order: reply = "Order not found."
                    else:
                        # STRICT CHECK
                        is_allowed = BusinessLogic.verify_user(order, args.get('user_email', email), "cancel")
                        if is_allowed:
                             reply = f"To cancel Order {order_id}, please email support@shelook.com."
                        else: 
                             reply = "⚠️ **Security Alert:** Email mismatch. Cannot process cancellation."

        return jsonify({"reply": reply, "found_email": email, "found_orderId": order_id})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"reply": "I'm having a brief technical moment. Please try again."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

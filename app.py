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
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL") # 1bp4n0-zv.myshopify.com
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")
PUBLIC_DOMAIN = "shelook.in"

client = Groq(api_key=GROQ_API_KEY)

# 2. HELPER FUNCTIONS
def extract_details(text):
    email = None
    order_id = None
    # Flexible email search
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    if email_match: email = email_match.group(0)
    # Flexible Order ID search (SL 1001 or SL1001)
    order_match = re.search(r'(SL\s*\d+)', text, re.IGNORECASE)
    if order_match: 
        # Remove spaces so "SL 1001" becomes "SL1001"
        order_id = order_match.group(1).upper().replace(" ", "")
    return email, order_id

def get_shopify_headers():
    return {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}

# 3. TOOLS

def find_product_link(query):
    # Fuzzy search for product
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/products.json?title={query}"
    try:
        response = requests.get(url, headers=get_shopify_headers())
        products = response.json().get('products', [])
        
        if not products:
            search_url = f"https://{PUBLIC_DOMAIN}/search?q={query}"
            return f"I couldn't find an exact match for '{query}', but you can browse our collection here: <br><a href='{search_url}' target='_blank' style='color:blue; text-decoration:underline;'>View {query} Collection</a>"
            
        product = products[0]
        product_url = f"https://{PUBLIC_DOMAIN}/products/{product['handle']}"
        image_url = ""
        if product.get('image'):
            image_url = product['image']['src']

        # Returns HTML with Image (if available) and Button
        html = f"I recommend our <b>{product['title']}</b>.<br>"
        if image_url:
            html += f"<img src='{image_url}' style='width:100%; border-radius:8px; margin:10px 0;'><br>"
        html += f"👉 <a href='{product_url}' target='_blank' style='background:#000; color:#fff; padding:8px 15px; border-radius:20px; text-decoration:none;'>View Product</a>"
        return html
    except Exception as e:
        return "I'm having trouble searching the catalog right now."

def check_status(order_id, user_email):
    # API Call to find order by name
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={order_id}&status=any"
    try:
        response = requests.get(url, headers=get_shopify_headers())
        data = response.json()
        
        if not data.get('orders'):
            return f"I searched for **{order_id}** but found nothing. Please check if there is a space or typo."
            
        order = data['orders'][0]
        
        # --- ROBUST EMAIL FINDER ---
        # We check 3 different fields where Shopify might hide the email
        found_emails = []
        
        # 1. Direct Email
        if order.get('email'): found_emails.append(order.get('email').lower().strip())
        
        # 2. Contact Email
        if order.get('contact_email'): found_emails.append(order.get('contact_email').lower().strip())
        
        # 3. Customer Record Email (Handle cases where customer is null)
        if order.get('customer') and order['customer'].get('email'):
            found_emails.append(order['customer']['email'].lower().strip())
            
        # Clean User Input
        input_email = user_email.lower().strip()
        
        # The Check
        if input_email not in found_emails:
            # SECURITY: Mask the email found to show user the hint without exposing full data
            hint = "No email found on order"
            if found_emails:
                real = found_emails[0]
                # Show first 2 chars and domain (e.g. su****@gmail.com)
                mask_at = real.find('@')
                if mask_at > 2:
                    hint = f"{real[:2]}****{real[mask_at:]}"
                else:
                    hint = "****" + real[mask_at:]
            
            return f"⚠️ **Mismatch:** The email you entered ({user_email}) does not match our records for {order_id}.<br>The order is linked to: **{hint}**."

        # Status Logic
        status = order.get('fulfillment_status') or "Unfulfilled"
        financial = order.get('financial_status') or "Pending"
        
        tracking_html = "No tracking info yet."
        if order.get('fulfillments'):
            t = order['fulfillments'][0]
            if t.get('tracking_url'):
                tracking_html = f"<a href='{t.get('tracking_url')}' target='_blank' style='color:blue; text-decoration:underline;'>Track Shipment</a>"
            else:
                tracking_html = t.get('tracking_number') or "Shipped"
        
        return f"📦 **Order {order['name']}**<br>Payment: {financial}<br>Status: {status}<br>Tracking: {tracking_html}"

    except Exception as e:
        print(f"ERROR Checking Status: {e}")
        return "I'm having a technical issue checking that order. Please try again."

def cancel_order(order_id, user_email):
     return f"To cancel order {order_id}, please email us directly at <a href='mailto:support@shelook.com'>support@shelook.com</a>."

# 4. CHAT ROUTE
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        msg = data.get('message', '')
        
        email = data.get('email') or extract_details(msg)[0]
        order_id = data.get('orderId') or extract_details(msg)[1]

        system_prompt = f"""
        You are the SHELOOK Jewelry Assistant.
        
        RULES:
        1. **Product Search:** ALWAYS use 'find_product_link' if user mentions a jewelry type (ring, anklet, etc).
        2. **Order Check:** User needs Order ID AND Email.
           - If missing, ask for them politely.
           - Once you have both, call 'check_status'.
        3. **Format:** Use HTML for bolding and links.

        Context: Email={email}, OrderID={order_id}
        """

        tools = [
            {"type": "function", "function": {"name": "check_status", "description": "Check status", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}},
            {"type": "function", "function": {"name": "find_product_link", "description": "Search product", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
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

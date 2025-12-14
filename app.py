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
# BLOCK 4: MAIN APP ROUTE (Fixed: Broad Search "Any Match")
# ==========================================
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        msg = data.get('message', '')
        history = data.get('history', []) 
        
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

        # 3. System Prompt (Simplified)
        system_prompt = f"""
        You are the SHELOOK Jewelry Assistant.

        **PHASE 1: THE GIFT FINDER**
        If user mentions "Gift", START this sequence. Ask ONE question at a time.
        
        1. **Step 1 (Budget):** If unknown, ask budget.
        2. **Step 2 (Who):** If unknown, ask "Man or Woman?".
        3. **Step 3 (Occasion):** If unknown, ask occasion.
        4. **Step 4 (Style):** If unknown, ask "Modern or Traditional?".
        5. **Step 5 (Results):** Once you have all 4, call 'find_product'.
           - Create a query string with KEYWORDS ONLY.
           - Example: "Women Silver Ring Modern" or "Men Chain Oxidized".

        **PHASE 2: SALES & STYLING:**
        - **Cross-Selling:** Suggest matching items.
        - **Ring Sizing:** Explain thread method. MUST call 'find_product' with query="Adjustable Ring".

        **PHASE 3: ORDER TASKS:**
        - Ask for Order ID -> Wait -> Ask for Email -> Wait.

        **GENERAL:** Use HTML formatting. Context: Email={email}, OrderID={order_id}
        """

        # 4. Construct Message List
        messages_payload = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": msg}]

        # 5. AI Call
        completion = client.chat.completions.create(
            messages=messages_payload,
            model="llama-3.3-70b-versatile",
            tools=tools,
            tool_choice="auto"
        )
        
        reply = completion.choices[0].message.content or ""
        tool_calls = completion.choices[0].message.tool_calls

        # 6. Tool Execution Logic (BROAD MATCH UPDATE)
        if tool_calls:
            for tool in tool_calls:
                fn = tool.function.name
                args = json.loads(tool.function.arguments)
                tool_result = ""
                
                try:
                    if fn == "find_product":
                        query_str = args.get('query', '')
                        all_prods = []
                        
                        # A. Split query into individual words (e.g. "Modern Women" -> ["Modern", "Women"])
                        keywords = query_str.split()
                        
                        # Filter out short words like "for", "a", "in" to save API calls
                        keywords = [k for k in keywords if len(k) > 2]
                        
                        # B. Search for EACH word separately
                        print(f"Searching keywords: {keywords}")
                        for word in keywords:
                            found = ShopifyClient.search_product(word)
                            if found:
                                all_prods.extend(found)
                        
                        # C. Search the Full Phrase too (just in case strict match is better)
                        full_match = ShopifyClient.search_product(query_str)
                        if full_match:
                            all_prods.extend(full_match)

                        # D. Deduplicate (Remove identical products)
                        unique_prods = []
                        seen_ids = set()
                        for p in all_prods:
                            # Use product ID if available, else use Title as unique key
                            p_id = p.get('id', p.get('title'))
                            if p_id not in seen_ids:
                                unique_prods.append(p)
                                seen_ids.add(p_id)

                        # E. Limit results (Top 10 to keep it clean)
                        final_list = unique_prods[:10]

                        # F. Final Fallback (If literally nothing matched any word)
                        if not final_list:
                             print("Zero matches for any keyword. Defaulting to 'Silver'.")
                             final_list = ShopifyClient.search_product("Silver")

                        tool_result = BusinessLogic.format_product_link(query_str, final_list)
                    
                    elif fn == "check_status":
                        if not order_id: tool_result = "Please provide your Order ID first."
                        elif not email: tool_result = "Please provide your Email Address."
                        else:
                            order = ShopifyClient.get_order(order_id)
                            if not order: tool_result = "Order not found."
                            else:
                                is_allowed = BusinessLogic.verify_user(order, args.get('user_email', email), "status")
                                if is_allowed: tool_result = BusinessLogic.format_status(order)
                                else: tool_result = "⚠️ Verification Failed. Email mismatch."

                    elif fn == "cancel_order":
                        if not order_id: tool_result = "Please provide your Order ID first."
                        elif not email: tool_result = "Please provide your Email Address."
                        else:
                            order = ShopifyClient.get_order(order_id)
                            if not order: tool_result = "Order not found."
                            else:
                                is_allowed = BusinessLogic.verify_user(order, args.get('user_email', email), "cancel")
                                if is_allowed: tool_result = f"To cancel Order {order_id}, please email support@shelook.com."
                                else: tool_result = "⚠️ **Security Alert:** Email mismatch. Cannot process cancellation."
                    
                    reply += f"<br><br>{tool_result}"
                    
                except Exception as tool_err:
                    print(f"Tool Error ({fn}): {tool_err}")
                    reply += f"<br>I couldn't find specific info for that."

        return jsonify({"reply": reply, "found_email": email, "found_orderId": order_id})

    except Exception as e:
        print(f"CRITICAL SERVER ERROR: {e}")
        return jsonify({"reply": "I'm having a brief technical moment. Please try again."})

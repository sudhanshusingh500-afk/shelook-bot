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
# BLOCK 4: MAIN APP ROUTE (Stable: Category Mapping Approach)
# ==========================================
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        msg = data.get('message', '')
        history = data.get('history', []) 
        
        # 1. Extract Details (Safe Mode)
        email = data.get('email')
        order_id = data.get('orderId')

        # 2. Define Tools
        tools = [
            {"type": "function", "function": {"name": "find_product", "description": "Search for jewelry", "parameters": {"type": "object", "properties": {"keywords": {"type": "string", "description": "Space-separated product keywords (e.g. 'Silver Ring Women')"}}, "required": ["keywords"]}}},
            {"type": "function", "function": {"name": "check_status", "description": "Check order status", "parameters": {"type": "object", "properties": {"user_email": {"type": "string"}}, "required": ["user_email"]}}}
        ]

        # 3. System Prompt (THE NEW STRATEGY)
        system_prompt = f"""
        You are the SHELOOK Jewelry Assistant.

        **STRATEGY: MAP OCCASIONS TO PRODUCTS**
        Do not search for "Birthday" or "Gift". Search for the *Object*.
        
        **MAPPING RULES:**
        - **Birthday:** Search "Pendant" or "Earrings" or "Charm".
        - **Anniversary:** Search "Ring" or "Mangalsutra" or "Necklace".
        - **Love/Girlfriend:** Search "Heart" or "Couple Ring".
        - **Budget < 2000:** Add "Silver" to the search (it's cheaper).

        **PHASE 1: GIFT FINDER**
        1. Ask Budget.
        2. Ask Who (Man/Woman).
        3. Ask Occasion.
        4. **EXECUTE:** Call 'find_product' using the Mapped Keywords.
           - Example: User="Birthday, Women". You Call keywords="Women Silver Pendant".

        **PHASE 2: GENERAL**
        - If asking for Ring Size, call 'find_product' with keywords="Adjustable Ring".
        - Use HTML formatting.
        """

        # 4. Construct Message
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

        # 6. Tool Execution (Defensive Coding)
        if tool_calls:
            for tool in tool_calls:
                fn = tool.function.name
                try:
                    args = json.loads(tool.function.arguments)
                    
                   # Inside your chat() function, under "if tool_calls:"

if fn == "find_product":
    raw_query = args.get('query', '')
    print(f"Original Query: {raw_query}")

    all_products = []
    
    # STRATEGY 1: Split query and search EACH word separately
    # "Modern Women Birthday" -> searches "Modern", then "Women", then "Birthday"
    keywords = raw_query.split()
    
    # Filter: Remove short/useless words to save API calls
    ignore_words = ["for", "the", "and", "with", "gift", "present"]
    keywords = [k for k in keywords if len(k) > 2 and k.lower() not in ignore_words]

    for word in keywords:
        found = ShopifyClient.search_product(word)
        if found:
            all_products.extend(found)
            
    # STRATEGY 2: If we found nothing yet, search "Silver" as a fallback
    if not all_products:
        print("No keyword matches. Defaulting to Silver.")
        all_products = ShopifyClient.search_product("Silver")

    # STRATEGY 3: Deduplicate (Remove exact duplicates)
    unique_products = []
    seen_ids = set()
    
    for p in all_products:
        # Use Product ID (or Title) to track uniqueness
        pid = p.get('id', p.get('title'))
        if pid not in seen_ids:
            unique_products.append(p)
            seen_ids.add(pid)
    
    # Limit to top 10 results to keep chat clean
    final_results = unique_products[:10]

    tool_result = BusinessLogic.format_product_link(raw_query, final_results)

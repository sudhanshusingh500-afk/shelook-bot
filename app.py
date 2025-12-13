import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app = Flask(__name__)
CORS(app)  # Allow your Shopify site to talk to this server

# 1. CONFIGURATION
# Render will pull these from your Environment Variables
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SHOPIFY_URL = os.environ.get("SHOPIFY_STORE_URL") # e.g. shelook.myshopify.com
SHOPIFY_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

# --- 2. THE HANDS (Shopify Functions) ---

def get_shopify_order(order_id):
    """Fetch order details from Shopify by Name (e.g., SL1001)"""
    url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders.json?name={order_id}&status=any"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        if not data.get('orders'):
            return None
        return data['orders'][0]
    except Exception as e:
        print(f"Shopify Error: {e}")
        return None

def check_order_status(order_id):
    order = get_shopify_order(order_id)
    if not order:
        return f"I could not find Order {order_id}. Please double-check the ID."

    fulfillment = order.get('fulfillment_status') or "Unfulfilled (Processing)"
    payment = order.get('financial_status')
    
    tracking_msg = "No tracking number yet."
    if order.get('fulfillments'):
        # Get the first fulfillment
        fulfillment_data = order['fulfillments'][0]
        tracking_number = fulfillment_data.get('tracking_number')
        tracking_url = fulfillment_data.get('tracking_url')
        
        if tracking_url:
            tracking_msg = f"Tracking Link: {tracking_url}"
        elif tracking_number:
            tracking_msg = f"Tracking Number: {tracking_number}"

    return (f"📦 **Order {order['name']} Status:**\n"
            f"- Status: {fulfillment}\n"
            f"- Payment: {payment}\n"
            f"- {tracking_msg}")

def try_cancel_order(order_id):
    order = get_shopify_order(order_id)
    if not order:
        return "Order not found."

    # POLICY: Cannot cancel if shipped
    if order.get('fulfillment_status') == 'fulfilled':
        return ("⚠️ **Cancellation Failed:**\n"
                "Your order has already been shipped. We cannot cancel it now. "
                "Please reach out to us for a return after delivery.")

    # Execute Cancellation
    try:
        cancel_url = f"https://{SHOPIFY_URL}/admin/api/2024-01/orders/{order['id']}/cancel.json"
        headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
        requests.post(cancel_url, headers=headers, json={})
        return ("✅ **Success:** Your order has been cancelled. "
                "You will receive a refund confirmation email shortly.")
    except Exception as e:
        return "❌ **Error:** Technical issue cancelling. Please email support@shelook.com."

# --- 3. THE BRAIN (Groq AI) ---

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message')
    email = data.get('email')
    order_id = data.get('orderId')

    # SYSTEM PROMPT
    system_prompt = f"""
    You are the SHELOOK Jewelry Assistant.
    
    GOALS:
    1. Answer general questions about jewelry, styling, and care friendly and briefly.
    2. Handle Order Tasks (Status, Cancel) strictly using tools.

    RULES:
    - If user asks for Status or Cancel, you MUST have their Email and Order ID.
    - If Email is missing -> Ask for it.
    - If Order ID is missing -> Ask for it.
    - If BOTH are present -> Use the Tool 'check_status' or 'cancel_order'.

    CONTEXT:
    - User Email: {email if email else "Unknown"}
    - User Order ID: {order_id if order_id else "Unknown"}
    """

    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_status",
                "description": "Check order status and tracking",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_order",
                "description": "Cancel an order if not shipped",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]

    try:
        # A. Ask Groq
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model="llama3-70b-8192",
            tools=tools,
            tool_choice="auto"
        )

        response_message = completion.choices[0].message
        reply = response_message.content
        tool_calls = response_message.tool_calls

        # B. If Groq wants to use a Tool
        if tool_calls:
            if not order_id:
                 reply = "I can help, but I need your Order ID (e.g., SL1001) first."
            else:
                tool_call_id = tool_calls[0].id
                function_name = tool_calls[0].function.name
                
                if function_name == "check_status":
                    reply = check_order_status(order_id)
                elif function_name == "cancel_order":
                    reply = try_cancel_order(order_id)

        return jsonify({"reply": reply})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"reply": "Sorry, my brain is offline. Please try again."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

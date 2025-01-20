from flask import Flask, request, jsonify, render_template, Response
import json
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import os
from flask_sqlalchemy import SQLAlchemy
import queue
import threading
import requests

from mpesa import MPesaClient, normalize_phone_number

# Load environment variables from .env file
load_dotenv()

# Retrieve the database connection string
database_url = os.getenv("DATABASE_URL", "sqlite:///mpesa.db")
if not database_url:
    raise RuntimeError("DATABASE_URL not configured. Please check your .env file.")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("mpesa_callbacks.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Global message queue for SSE
message_queue = queue.Queue()

# Define the Transaction model
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    checkout_request_id = db.Column(db.String(100), nullable=True)
    result_code = db.Column(db.Integer, nullable=False)
    result_desc = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    mpesa_receipt_number = db.Column(db.String(100), nullable=True)
    transaction_date = db.Column(db.String(20), nullable=True)
    phone_number = db.Column(db.String(15), nullable=True)

def verify_recaptcha(recaptcha_response: str) -> bool:
    recaptcha_secret = os.getenv("RECAPTCHA_SECRET_KEY")
    if not recaptcha_secret:
        logger.error("RECAPTCHA_SECRET_KEY not configured. Please check your .env file.")
        return False

    payload = {
        'secret': recaptcha_secret,
        'response': recaptcha_response
    }
    response = requests.post("https://www.google.com/recaptcha/api/siteverify", data=payload)
    result = response.json()

    return result.get("success", False)

# MPesa Callback Processor
class MPesaCallback:
    @staticmethod
    def process_callback(callback_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            body = callback_data.get("Body", {})
            stkCallback = body.get("stkCallback", {})

            # Extract transaction details
            checkout_request_id = stkCallback.get("CheckoutRequestID")
            result_code = stkCallback.get("ResultCode")
            result_desc = stkCallback.get("ResultDesc")

            transaction_details = {
                "checkout_request_id": checkout_request_id,
                "result_code": result_code,
                "result_desc": result_desc,
                "amount": None,
                "mpesa_receipt_number": None,
                "transaction_date": None,
                "phone_number": None,
            }

            # If successful, process metadata
            if result_code == 0:
                metadata_items = stkCallback.get("CallbackMetadata", {}).get("Item", [])
                for item in metadata_items:
                    name = item.get("Name")
                    value = item.get("Value")
                    if name == "Amount":
                        transaction_details["amount"] = value
                    elif name == "MpesaReceiptNumber":
                        transaction_details["mpesa_receipt_number"] = value
                    elif name == "TransactionDate":
                        transaction_details["transaction_date"] = value
                    elif name == "PhoneNumber":
                        transaction_details["phone_number"] = value

            logger.info(f"Processed callback: {transaction_details}")
            return transaction_details

        except Exception as e:
            logger.error(f"Error processing callback: {e}")
            raise ValueError("Invalid callback data structure.")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/initiate_payment", methods=["POST"])
def initiate_payment():
    try:
        data = request.json
        phone_number = data.get("phone_number")
        amount = data.get("amount")
        recaptcha_response = data.get("recaptcha_response")

        # Validate inputs
        if not phone_number or not amount:
            return jsonify({"error": "Phone number and amount are required"}), 400

        # Normalize phone number
        try:
            phone_number = normalize_phone_number(phone_number)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        # Validate reCAPTCHA
        if not verify_recaptcha(recaptcha_response):
            return jsonify({"error": "Invalid reCAPTCHA. Please try again."}), 400

        # Convert amount to float
        try:
            amount = float(amount)
        except ValueError:
            return jsonify({"error": "Invalid amount format"}), 400

        # Initialize MPesa client
        mpesa_client = MPesaClient()
        checkout_request_id = mpesa_client.send_stk_push(phone_number, amount)

        return jsonify({"checkout_request_id": checkout_request_id}), 200

    except Exception as e:
        logger.error(f"Error initiating payment: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/check_status", methods=["POST"])
def check_status():
    try:
        data = request.json
        checkout_request_id = data.get("checkout_request_id")

        if not checkout_request_id:
            return jsonify({"error": "Checkout request ID is required"}), 400

        # Initialize MPesa client
        mpesa_client = MPesaClient()
        status = mpesa_client.query_transaction_status(checkout_request_id)

        return jsonify(status), 200

    except Exception as e:
        logger.error(f"Error checking status: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():
    try:
        callback_data = request.get_json()
        logger.info(f"Received callback: {json.dumps(callback_data, indent=2)}")

        # Process the callback to extract transaction details
        transaction_details = MPesaCallback.process_callback(callback_data)
        
        # Log processed transaction details
        logger.info(f"Processed callback for CheckoutRequestID: {transaction_details['checkout_request_id']}")
        logger.info(f"Processed transaction details: {json.dumps(transaction_details, indent=2)}")

        # Store the transaction in the database
        store_transaction_details(transaction_details)

        # Broadcast the transaction details to all connected clients
        message_queue.put(transaction_details)

        # Return transaction details as response
        return jsonify({
            "ResultCode": 0,
            "ResultDesc": "Callback processed successfully",
            "transaction_details": transaction_details
        }), 200
    except Exception as e:
        logger.error(f"Callback processing failed: {e}")
        return jsonify({"ResultCode": 1, "ResultDesc": str(e)}), 500

@app.route("/stream")
def stream():
    def event_stream():
        try:
            while True:
                # Wait for a new message in the queue
                transaction_details = message_queue.get(timeout=10)
                yield f"data: {json.dumps(transaction_details)}\n\n"
        except queue.Empty:
            # If the queue is empty, send a keep-alive comment
            yield ": keep-alive\n\n"
        except Exception as e:
            logger.error(f"Error in event stream: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")

def store_transaction_details(transaction_details: Dict[str, Any]) -> None:
    try:
        transaction = Transaction(
            checkout_request_id=transaction_details["checkout_request_id"],
            result_code=transaction_details["result_code"],
            result_desc=transaction_details["result_desc"],
            amount=transaction_details.get("amount"),
            mpesa_receipt_number=transaction_details.get("mpesa_receipt_number"),
            transaction_date=transaction_details.get("transaction_date"),
            phone_number=transaction_details.get("phone_number"),
        )
        db.session.add(transaction)
        db.session.commit()
        logger.info(f"Stored transaction: {transaction_details['checkout_request_id']}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to store transaction: {e}")
        raise e

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(port=5000, debug=True)
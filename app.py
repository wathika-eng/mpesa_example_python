from flask import Flask, request, jsonify
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv
import os
from flask_sqlalchemy import SQLAlchemy

# Load environment variables from .env file
load_dotenv()

# Retrieve the PostgreSQL connection string
database_url = os.getenv("DATABASE_URL")

if not database_url:
    database_url = "sqlite:///mpesa.db"
    print(f"Using default SQLite database: {database_url}")

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


class MPesaCallback:
    @staticmethod
    def process_callback(callback_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            body = callback_data.get("Body", {})
            stkCallback = body.get("stkCallback", {})

            checkout_request_id = stkCallback.get("CheckoutRequestID")
            result_code = stkCallback.get("ResultCode")
            result_desc = stkCallback.get("ResultDesc")

            if not checkout_request_id or result_code is None or not result_desc:
                raise ValueError("Missing required fields in callback data")

            transaction_details = {
                "checkout_request_id": checkout_request_id,
                "result_code": result_code,
                "result_desc": result_desc,
                "amount": None,
                "mpesa_receipt_number": None,
                "transaction_date": None,
                "phone_number": None,
            }

            if result_code == 0:  # Successful transaction
                callback_metadata = stkCallback.get("CallbackMetadata", {}).get(
                    "Item", []
                )
                for item in callback_metadata:
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

            logger.info(
                f"Processed callback for CheckoutRequestID: {checkout_request_id}"
            )
            return transaction_details

        except Exception as e:
            logger.error(f"Error processing callback data: {e}")
            raise


@app.route("/test", methods=["GET"])
def test():
    return jsonify({"message": "Hello, World!"})


@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():
    try:
        callback_data = request.get_json()
        logger.info(f"Received callback: {json.dumps(callback_data, indent=2)}")

        transaction_details = MPesaCallback.process_callback(callback_data)
        logger.info(
            f"Processed transaction details: {json.dumps(transaction_details, indent=2)}"
        )

        store_transaction_details(transaction_details)

        return jsonify(
            {"ResultCode": 0, "ResultDesc": "Callback processed successfully"}
        ), 200

    except Exception as e:
        logger.error(f"Callback processing failed: {e}")
        return jsonify(
            {"ResultCode": 1, "ResultDesc": f"Callback processing failed: {e}"}
        ), 500


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
        logger.info(
            f"Transaction {transaction_details['checkout_request_id']} stored successfully"
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to store transaction details: {e}")
        raise


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(port=5000, debug=True)

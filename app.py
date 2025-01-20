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

if database_url:
    print(f"Database URL: {database_url}")
else:
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

    def __init__(
        self,
        checkout_request_id,
        result_code,
        result_desc,
        amount=None,
        mpesa_receipt_number=None,
        transaction_date=None,
        phone_number=None,
    ):
        self.checkout_request_id = checkout_request_id
        self.result_code = result_code
        self.result_desc = result_desc
        self.amount = amount
        self.mpesa_receipt_number = mpesa_receipt_number
        self.transaction_date = transaction_date
        self.phone_number = phone_number


class MPesaCallback:
    @staticmethod
    def process_callback(callback_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the callback data from M-Pesa and extract relevant transaction details.

        Args:
            callback_data (Dict[str, Any]): Raw callback data from M-Pesa

        Returns:
            Dict[str, Any]: Processed transaction details
        """
        try:
            body = callback_data.get("Body", {})
            stkCallback = body.get("stkCallback", {})

            # Extract basic transaction details
            checkout_request_id = stkCallback.get("CheckoutRequestID")
            result_code = stkCallback.get("ResultCode")
            result_desc = stkCallback.get("ResultDesc")

            # Validate required fields
            if not checkout_request_id or not result_code or not result_desc:
                raise ValueError("Missing required fields in callback data")

            # Initialize transaction details
            transaction_details = {
                "checkout_request_id": checkout_request_id,
                "result_code": result_code,
                "result_desc": result_desc,
                "amount": None,
                "mpesa_receipt_number": None,
                "transaction_date": None,
                "phone_number": None,
            }

            # If transaction was successful, extract additional details
            if result_code == 0:  # Successful transaction
                callback_metadata = stkCallback.get("CallbackMetadata", {}).get(
                    "Item", []
                )

                # Process callback metadata
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
            raise ValueError(f"Invalid callback data structure: {e}")


# Flask Routes
@app.route("/test", methods=["GET"])
def test():
    return jsonify({"message": "Hello, World!"})


@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():
    """
    Flask endpoint to handle M-Pesa callbacks.
    """
    try:
        callback_data = request.get_json()
        logger.info(f"Received callback: {json.dumps(callback_data, indent=2)}")

        # Process the callback
        transaction_details = MPesaCallback.process_callback(callback_data)
        logger.info(
            f"Processed transaction details: {json.dumps(transaction_details, indent=2)}"
        )

        # Store transaction details in the database
        store_transaction_details(transaction_details)

        return jsonify(
            {"ResultCode": 0, "ResultDesc": "Callback processed successfully"}
        ), 200

    except Exception as e:
        logger.error(f"Callback processing failed: {e}")
        return jsonify(
            {"ResultCode": 1, "ResultDesc": f"Callback processing failed: {str(e)}"}
        ), 500


def store_transaction_details(transaction_details: Dict[str, Any]) -> None:
    """
    Store transaction details in the database.

    Args:
        transaction_details (Dict[str, Any]): Processed transaction details
    """
    try:
        # Validate required fields
        if (
            not transaction_details.get("checkout_request_id")
            or not transaction_details.get("result_code")
            or not transaction_details.get("result_desc")
        ):
            raise ValueError("Missing required transaction details")

        # Create a new Transaction object
        transaction = Transaction(
            checkout_request_id=transaction_details["checkout_request_id"],
            result_code=transaction_details["result_code"],
            result_desc=transaction_details["result_desc"],
            amount=transaction_details.get("amount"),
            mpesa_receipt_number=transaction_details.get("mpesa_receipt_number"),
            transaction_date=transaction_details.get("transaction_date"),
            phone_number=transaction_details.get("phone_number"),
        )

        # Add and commit the transaction to the database
        db.session.add(transaction)
        db.session.commit()
        logger.info(
            f"Transaction {transaction_details['checkout_request_id']} stored successfully"
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to store transaction details: {e}")
        raise e


# Run the application
if __name__ == "__main__":
    from app import app, db

    with app.app_context():
        db.create_all()  # Create database tables if they don't exist
    app.run(port=5000, debug=True)

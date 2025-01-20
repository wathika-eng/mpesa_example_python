from flask import Flask, request, jsonify
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("mpesa_callbacks.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# File to store transaction details
TRANSACTION_STORE = "transactions.json"

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
                callback_metadata = stkCallback.get("CallbackMetadata", {}).get("Item", [])
                
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
            
            logger.info(f"Processed callback for CheckoutRequestID: {checkout_request_id}")
            return transaction_details
            
        except Exception as e:
            logger.error(f"Error processing callback data: {e}")
            raise ValueError(f"Invalid callback data structure: {e}")

@app.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    """
    Flask endpoint to handle M-Pesa callbacks.
    """
    try:
        callback_data = request.get_json()
        logger.info(f"Received callback: {json.dumps(callback_data, indent=2)}")
        
        # Process the callback
        transaction_details = MPesaCallback.process_callback(callback_data)
        
        # Store transaction details in JSON
        store_transaction_details(transaction_details)
        
        return jsonify({
            "ResultCode": 0,
            "ResultDesc": "Callback processed successfully"
        }), 200
        
    except Exception as e:
        logger.error(f"Callback processing failed: {e}")
        return jsonify({
            "ResultCode": 1,
            "ResultDesc": f"Callback processing failed: {str(e)}"
        }), 500

def store_transaction_details(transaction_details: Dict[str, Any]) -> None:
    """
    Store transaction details in a JSON file.
    
    Args:
        transaction_details (Dict[str, Any]): Processed transaction details
    """
    try:
        # Read existing transactions from the file
        try:
            with open(TRANSACTION_STORE, "r") as f:
                transactions = json.load(f)
        except FileNotFoundError:
            transactions = []

        # Append the new transaction details
        transactions.append(transaction_details)
        
        # Write back to the file
        with open(TRANSACTION_STORE, "w") as f:
            json.dump(transactions, f, indent=2)
        
        logger.info(f"Transaction details saved: {transaction_details}")
    except Exception as e:
        logger.error(f"Failed to store transaction details: {e}")

if __name__ == "__main__":
    app.run(port=5000, debug=True)

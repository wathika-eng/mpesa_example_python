import base64
import datetime
import json
import os
import sys
import time
import logging
from typing import Dict, Optional
from flask import jsonify
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("mpesa_transactions.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class MPesaError(Exception):
    """Custom exception for M-Pesa API related errors."""

    pass


class MPesaClient:
    def __init__(self):
        """
        Initialize MPesa client with environment configurations.
        Validates critical environment variables on instantiation.
        """
        load_dotenv()

        # Mandatory environment variables
        required_envs = [
            "MPESA_BASE_API_URL",
            "SHORTCODE",
            "CONSUMER_KEY",
            "CONSUMER_SECRET",
            "PASSKEY",
            "CALLBACK_URL",
        ]

        for env in required_envs:
            if not os.environ.get(env):
                raise ValueError(f"Missing required environment variable: {env}")

        self.base_url = os.environ.get("MPESA_BASE_API_URL")
        self.short_code = os.environ.get("SHORTCODE")
        self.consumer_key = os.environ.get("CONSUMER_KEY")
        self.consumer_secret = os.environ.get("CONSUMER_SECRET")
        self.passkey = os.environ.get("PASSKEY")
        self.callback_url = os.environ.get("CALLBACK_URL")

        self.token = None
        self.token_expires_at = None

    def _generate_password(self) -> str:
        """
        Generate base64 encoded password for API authentication.

        Returns:
            str: Base64 encoded password
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        password_string = f"{self.short_code}{self.passkey}{timestamp}"
        return base64.b64encode(password_string.encode("utf-8")).decode("utf-8")

    def _get_mpesa_token(self) -> str:
        """
        Retrieve OAuth token, with smart caching to minimize unnecessary token requests.

        Returns:
            str: Valid access token

        Raises:
            MPesaError: If token generation fails
        """
        # Check if existing token is still valid
        if (
            self.token
            and self.token_expires_at
            and datetime.datetime.now() < self.token_expires_at
        ):
            return self.token

        try:
            url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
            response = requests.get(
                url,
                auth=HTTPBasicAuth(self.consumer_key, self.consumer_secret),
                timeout=30,
            )
            response.raise_for_status()

            token_data = response.json()
            self.token = token_data.get("access_token")

            # Set token expiration (usually 1 hour, add some buffer)
            self.token_expires_at = datetime.datetime.now() + datetime.timedelta(
                minutes=50
            )

            logger.info("Successfully generated new M-Pesa API token")
            return self.token

        except requests.RequestException as e:
            logger.error(f"Token generation failed: {e}")
            raise MPesaError(f"Failed to generate M-Pesa token: {e}")

    def send_stk_push(
        self,
        phone_number: str,
        amount: int,
        transaction_desc: str = "Payment Transaction",
    ) -> str:
        """
        Initiate STK push transaction with comprehensive error handling.

        Args:
            phone_number (str): Customer's phone number
            amount (int): Transaction amount
            transaction_desc (str, optional): Transaction description

        Returns:
            str: Checkout request ID

        Raises:
            MPesaError: For various API or validation errors
        """
        # Input validation
        if not phone_number or not phone_number.startswith("254"):
            try:
                phone_number = normalize_phone_number(phone_number)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            
        if amount <= 0:
            raise ValueError("Amount must be a positive number")

        try:
            token = self._get_mpesa_token()
            headers = {"Authorization": f"Bearer {token}"}

            payload = {
                "BusinessShortCode": self.short_code,
                "Password": self._generate_password(),
                "Timestamp": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
                "TransactionType": os.environ.get(
                    "TRANS_TYPE", "CustomerPayBillOnline"
                ),
                "Amount": amount,
                "PartyA": phone_number,
                "PartyB": os.environ.get("PARTY_B", self.short_code),
                "PhoneNumber": phone_number,
                "CallBackURL": self.callback_url,
                "AccountReference": transaction_desc[:12],  # Truncate if too long
                "TransactionDesc": transaction_desc,
            }

            url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            resp_data = response.json()
            checkout_request_id = resp_data.get("CheckoutRequestID")

            if not checkout_request_id:
                raise MPesaError("No CheckoutRequestID received")

            logger.info(
                f"STK Push initiated successfully. CheckoutRequestID: {checkout_request_id}"
            )
            return checkout_request_id

        except requests.RequestException as e:
            logger.error(f"STK Push request failed: {e}")
            raise MPesaError(f"STK Push request failed: {e}")

    def query_transaction_status(self, checkout_request_id: str) -> Dict[str, str]:
        """
        Query transaction status with enhanced retry logic and structured response.

        Args:
            checkout_request_id (str): CheckoutRequestID received from STK Push.

        Returns:
            Dict[str, str]: Transaction status details.

        Raises:
            MPesaError: If the query fails after retries.
        """
        max_retries = 3
        retry_delay = 10  # seconds

        for attempt in range(max_retries):
            try:
                token = self._get_mpesa_token()
                headers = {"Authorization": f"Bearer {token}"}
                payload = {
                    "BusinessShortCode": self.short_code,
                    "Password": self._generate_password(),
                    "Timestamp": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
                    "CheckoutRequestID": checkout_request_id,
                }
                url = f"{self.base_url}/mpesa/stkpushquery/v1/query"

                response = requests.post(url, json=payload, headers=headers, timeout=30)

                if response.status_code == 500:
                    logger.warning(
                        f"Attempt {attempt + 1}: Server Error - Retrying in {retry_delay} seconds"
                    )
                    time.sleep(retry_delay)
                    continue

                response.raise_for_status()

                status_data = response.json()
                result_code = status_data.get("ResultCode")
                result_desc = status_data.get("ResultDesc", "No description provided")

                logger.info(
                    f"Transaction query response: ResultCode={result_code}, ResultDesc={result_desc}"
                )

                return {
                    "result_code": result_code,
                    "result_desc": result_desc,
                    "status_message": status_data.get("statusMessage", "No message"),
                    "metadata": status_data.get("CallbackMetadata", {}),
                }

            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Transaction status query failed after {max_retries} attempts: {e}"
                    )
                    raise MPesaError(f"Persistent API error: {e}")

                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(retry_delay)

        raise MPesaError("Unable to query transaction status after maximum retries")

def normalize_phone_number(phone_number: str) -> str:
    """
    Normalize the phone number to start with 254.
    Supports inputs like +254..., 07..., or 7...
    """
    # Remove any non-digit characters (e.g., +, spaces)
    phone_number = ''.join(filter(str.isdigit, phone_number))

    # Check if the number starts with 254, 07, or 7
    if phone_number.startswith('254'):
        return phone_number  # Already in the correct format
    elif phone_number.startswith('07') or phone_number.startswith('7'):
        return '254' + phone_number.lstrip('07')  # Convert to 254 format
    else:
        raise ValueError("Invalid phone number format. Must start with +254, 07, or 7.")

def main():
    """
    Main execution method with robust error handling and user feedback.
    """
    try:
        mpesa_client = MPesaClient()

        # Example transaction, change as needed
        phone_number = "254746554245"
        amount = 1
        transaction_desc = "Test Payment"

        # Initiate STK Push
        checkout_id = mpesa_client.send_stk_push(
            phone_number=phone_number, amount=amount, transaction_desc=transaction_desc
        )

        # Wait and check transaction status
        max_retries = 5
        retry_delay = 30  # seconds

        for attempt in range(max_retries):
            try:
                status = mpesa_client.query_transaction_status(checkout_id)

                if status["result_code"] == "0":  # Success
                    logger.info(f"🎉 Transaction Successful: {status['result_desc']}")
                    break
                elif status["result_code"] in {"1", "1032"}:  # Common failures
                    logger.warning(f"Transaction Failed: {status['result_desc']}")
                    break
                else:
                    logger.info(f"Attempt {attempt + 1}: {status['status_message']}")
                    time.sleep(retry_delay)

            except MPesaError as e:
                logger.error(f"Status check error: {e}")
                break

    except Exception as e:
        logger.critical(f"Unhandled error in M-Pesa transaction: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

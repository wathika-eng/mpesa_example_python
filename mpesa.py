import base64
import datetime
import json
import os
import sys
import time
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

MPESA_BASE_API_URL = os.environ.get("MPESA_BASE_API_URL")
short_code = os.environ.get("SHORTCODE")
consumer_key = os.environ.get("CONSUMER_KEY")
consumer_secret = os.environ.get("CONSUMER_SECRET")
passkey = os.environ.get("PASSKEY")
timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
password = base64.b64encode(f"{short_code}{passkey}{timestamp}".encode("utf-8")).decode(
    "utf-8"
)
callback_url = os.environ.get("CALLBACK_URL")

log_file = "transaction_log.json"


def get_mpesa_token(consumerKey=None, consumerSecret=None):
    """
    Generates an OAuth token required for making API requests to the MPESA API.

    Args:
        consumerKey (str): The consumer key for MPESA API authentication.
        consumerSecret (str): The consumer secret for MPESA API authentication.

    Returns:
        str: An access token for authenticating requests.

    Raises:
        Exception: If the API call fails, an exception with the response error message is raised.
    """
    url = f"{MPESA_BASE_API_URL}/oauth/v1/generate?grant_type=client_credentials"
    resp = requests.get(
        url, auth=HTTPBasicAuth(consumerKey, consumerSecret), timeout=60
    )
    if resp.status_code != 200:
        raise Exception(f"Failed to get token: {resp.text}")

    return resp.json().get("access_token")


def log_to_file(data):
    """
    Appends a dictionary of transaction data to a JSON log file with a timestamp.

    Args:
        data (dict): The data to be logged, including API response and other relevant info.

    Raises:
        IOError: If writing to the log file fails.
    """
    data["timestamp"] = datetime.datetime.now().isoformat()
    try:
        with open(log_file, "a") as file:
            file.write(json.dumps(data, indent=4) + "\n")
    except IOError as e:
        print(f"Failed to write to log file: {e}")


def send_stk_push():
    """
    Initiates an STK push transaction request via MPESA API.

    Returns:
        str: The CheckoutRequestID returned from the MPESA API, used to query transaction status.

    Logs:
        The initial STK push response is logged to the transaction log file.
    """
    token = get_mpesa_token(consumer_key, consumer_secret)
    headers = {"Authorization": f"Bearer {token}"}

    phone_number = "254746554245"
    amount: int = 1
    trans_ref = "Testing Daraja API"

    payload = {
        "BusinessShortCode": short_code,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": os.environ.get("TRANS_TYPE"),
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": os.environ.get("PARTY_B", short_code),
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": trans_ref,
        "TransactionDesc": "Testing Daraja API",
    }

    url = f"{MPESA_BASE_API_URL}/mpesa/stkpush/v1/processrequest"
    resp = requests.post(url, json=payload, headers=headers)
    json_resp = resp.json()
    print("STK Push Response:", json_resp)

    log_to_file({"type": "STK Push Response", "data": json_resp})

    return json_resp.get("CheckoutRequestID")


def query_status(checkout_request_id):
    """
    Queries the current status of an STK push transaction.

    Args:
        checkout_request_id (str): The CheckoutRequestID of the transaction to query.

    Returns:
        bool: True if the transaction completed successfully, False otherwise.

    Logs:
        Each query status response is logged to the transaction log file.
    """
    url = f"{MPESA_BASE_API_URL}/mpesa/stkpushquery/v1/query"

    payload = {
        "BusinessShortCode": short_code,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }

    token = get_mpesa_token(consumer_key, consumer_secret)
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.post(url, json=payload, headers=headers)
    json_resp = resp.json()
    print("Query Status Response:", json_resp)

    log_to_file({"type": "Query Status Response", "data": json_resp})

    result_code = json_resp.get("ResultCode")
    result_desc = json_resp.get("ResultDesc")

    if result_code == 0:
        print("Transaction successful.")
        return True
    elif result_code == 1:
        print(f"Transaction failed: {result_desc}")
        sys.exit("Exiting program due to transaction failure.")
    else:
        print(f"Transaction status unknown: {result_desc}")
        return False


"""
initiate an STK push transaction and query its status until completion.
"""
checkout_request_id = send_stk_push()

time.sleep(10)
while not query_status(checkout_request_id):
    time.sleep(30)
print("Transaction completed.")


import base64
import datetime
import os
import requests
from requests.auth import HTTPBasicAuth

from dotenv import load_dotenv
load_dotenv()

MPESA_BASE_API_URL = os.environ.get("MPESA_BASE_API_URL")

short_code = os.environ.get("SHORTCODE")
consumer_key = os.environ.get("CONSUMER_KEY")
consumer_secret = os.environ.get("CONSUMER_SECRET")
passkey = os.environ.get("PASSKEY")

timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
password = base64.b64encode(f"{short_code}{passkey}{timestamp}".encode('utf-8')).decode('utf-8')
callback_url = os.environ.get("CALLBACK_URL")


def get_mpesa_token(consumerKey=None, consumerSecret=None):
    url = f"{MPESA_BASE_API_URL}/oauth/v1/generate?grant_type=client_credentials"
    resp = requests.get(url, auth=HTTPBasicAuth(
        consumerKey, consumerSecret), timeout=60)
    if not resp.status_code == 200:
        raise Exception(resp.text)

    access_token = resp.json().get('access_token')
    expires_in = resp.json().get('expires_in')
    return access_token


def send_stk_push():
    token = get_mpesa_token(consumer_key, consumer_secret)
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    phone_number = "STK PUSH phone number"
    amount = "amount"
    trans_ref = "your reference"

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
        "TransactionDesc": f"a description"
    }

    url = f"{MPESA_BASE_API_URL}/mpesa/stkpush/v1/processrequest"
    resp = requests.post(url, json=payload, headers=headers)
    json_resp = resp.json()
    print(json_resp)


def query_status(self):
        url = f"{MPESA_BASE_API_URL}/mpesa/stkpushquery/v1/query"

        payload = {
            "BusinessShortCode": short_code,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": "" #STK_PUSH request ID from response
        }

        token = get_mpesa_token(consumer_key, consumer_secret)
        headers = {
            "Authorization": f"Bearer {token}"
        }

        resp = requests.post(url, json=payload, headers=headers)
        json_resp = resp.json()
        print(json_resp)
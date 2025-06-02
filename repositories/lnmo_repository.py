import base64
import requests
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Transaction, TransactionStatus
from typing import Dict, Any
import os
import logging

logger = logging.getLogger(__name__)

class LNMORepository:
    # Load configurations from environment variables (no defaults to enforce .env)
    MPESA_LNMO_CONSUMER_KEY = os.getenv("MPESA_LNMO_CONSUMER_KEY")
    MPESA_LNMO_CONSUMER_SECRET = os.getenv("MPESA_LNMO_CONSUMER_SECRET")
    MPESA_LNMO_ENVIRONMENT = os.getenv("MPESA_LNMO_ENVIRONMENT", "sandbox")
    MPESA_LNMO_PASS_KEY = os.getenv("MPESA_LNMO_PASS_KEY")
    MPESA_LNMO_SHORT_CODE = os.getenv("MPESA_LNMO_SHORT_CODE", "174379")
    MPESA_LNMO_CALLBACK_URL = os.getenv("MPESA_LNMO_CALLBACK_URL")

    def __init__(self):
        # Validate required environment variables
        required_vars = [
            self.MPESA_LNMO_CONSUMER_KEY,
            self.MPESA_LNMO_CONSUMER_SECRET,
            self.MPESA_LNMO_PASS_KEY,
            self.MPESA_LNMO_CALLBACK_URL
        ]
        if not all(required_vars):
            missing = [
                name for name, value in [
                    ("MPESA_LNMO_CONSUMER_KEY", self.MPESA_LNMO_CONSUMER_KEY),
                    ("MPESA_LNMO_CONSUMER_SECRET", self.MPESA_LNMO_CONSUMER_SECRET),
                    ("MPESA_LNMO_PASS_KEY", self.MPESA_LNMO_PASS_KEY),
                    ("MPESA_LNMO_CALLBACK_URL", self.MPESA_LNMO_CALLBACK_URL)
                ] if not value
            ]
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    async def transact(self, data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """Handle MPESA LNMO transaction"""
        try:
            endpoint = f"https://{self.MPESA_LNMO_ENVIRONMENT}.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
            headers = {
                "Authorization": f"Bearer {self.generate_access_token()}",
                "Content-Type": "application/json",
            }
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            payload = {
                "BusinessShortCode": self.MPESA_LNMO_SHORT_CODE,
                "Password": self.generate_password(timestamp),
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": str(data["Amount"]),
                "PartyA": data["PhoneNumber"],
                "PartyB": self.MPESA_LNMO_SHORT_CODE,
                "PhoneNumber": data["PhoneNumber"],
                "CallBackURL": self.MPESA_LNMO_CALLBACK_URL,
                "AccountReference": data["AccountReference"],
                "TransactionDesc": f"Payment for order {data['AccountReference']}",
            }

            response = requests.post(endpoint, json=payload, headers=headers)
            logger.info(f"STK Push request: endpoint={endpoint}, payload={payload}")
            logger.info(f"STK Push response: status={response.status_code}, text={response.text}")

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text or 'No response body'}")

            try:
                response_data = response.json()
            except ValueError as e:
                raise Exception(f"Invalid JSON response: {response.text}") from e

            if "errorCode" in response_data:
                raise Exception(f"M-Pesa API error: {response_data.get('errorMessage', 'Unknown error')}")

            # Save transaction to the database
            transaction = Transaction(
                _pid=data["pid"],
                party_a=data["PhoneNumber"],
                party_b=self.MPESA_LNMO_SHORT_CODE,
                account_reference=data["AccountReference"],
                transaction_category=0,  # Adjust if enums are used
                transaction_type=1,      # Adjust if enums are used
                transaction_channel=1,   # Adjust if enums are used
                transaction_aggregator=0,# Adjust if enums are used
                transaction_id=response_data.get("CheckoutRequestID"),
                transaction_amount=data["Amount"],
                transaction_code=None,
                transaction_timestamp=datetime.now(),
                transaction_details=f"Payment for order {data['AccountReference']}",
                _feedback=response_data,
                _status=TransactionStatus.PENDING,
                order_id=data["order_id"],
                user_id=data["user_id"]
            )
            db.add(transaction)
            await db.commit()
            await db.refresh(transaction)

            logger.info(f"Transaction saved: ID={transaction.transaction_id}")
            return response_data

        except Exception as e:
            logger.error(f"Error initiating M-Pesa transaction: {str(e)}")
            raise

    async def query(self, transaction_id: str, db: AsyncSession) -> Dict[str, Any]:
        """Query MPESA LNMO transaction status"""
        try:
            endpoint = f"https://{self.MPESA_LNMO_ENVIRONMENT}.safaricom.co.ke/mpesa/stkpushquery/v1/query"
            headers = {
                "Authorization": f"Bearer {self.generate_access_token()}",
                "Content-Type": "application/json",
            }
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            payload = {
                "BusinessShortCode": self.MPESA_LNMO_SHORT_CODE,
                "Password": self.generate_password(timestamp),
                "Timestamp": timestamp,
                "CheckoutRequestID": transaction_id,
            }

            response = requests.post(endpoint, json=payload, headers=headers)
            logger.info(f"Query response: status={response.status_code}, text={response.text}")
            response_data = response.json()
            return response_data
        except Exception as e:
            logger.error(f"Error querying M-Pesa transaction: {str(e)}")
            raise

    async def callback(self, data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """Handle MPESA callback"""
        try:
            checkout_request_id = data["Body"]["stkCallback"]["CheckoutRequestID"]
            result = await db.execute(
                select(Transaction).where(Transaction.transaction_id == checkout_request_id)
            )
            transaction = result.scalars().first()

            if not transaction:
                logger.error(f"Transaction not found for CheckoutRequestID: {checkout_request_id}")
                raise Exception("Transaction not found")

            transaction._feedback = data
            result_code = data["Body"]["stkCallback"]["ResultCode"]

            if result_code == 0:
                transaction._status = TransactionStatus.ACCEPTED
                callback_metadata = data["Body"]["stkCallback"].get("CallbackMetadata")
                if callback_metadata:
                    items = callback_metadata.get("Item", [])
                    for item in items:
                        if item.get("Name") == "MpesaReceiptNumber" and "Value" in item:
                            transaction.transaction_code = item["Value"]
                            break
            else:
                transaction._status = TransactionStatus.REJECTED

            await db.commit()
            await db.refresh(transaction)
            logger.info(f"Callback processed for transaction {checkout_request_id}")
            return data
        except Exception as e:
            logger.error(f"Error processing M-Pesa callback: {str(e)}")
            raise

    def generate_access_token(self) -> str:
        """Generate an access token for the MPESA API"""
        try:
            endpoint = f"https://{self.MPESA_LNMO_ENVIRONMENT}.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
            credentials = f"{self.MPESA_LNMO_CONSUMER_KEY}:{self.MPESA_LNMO_CONSUMER_SECRET}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/json",
            }

            logger.info(f"Requesting access token from {endpoint}")
            response = requests.get(endpoint, headers=headers, timeout=10)
            logger.info(f"Access token response: status={response.status_code}, text={response.text}")

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text or 'No response body'}")

            try:
                response_data = response.json()
            except ValueError as e:
                raise Exception(f"Invalid JSON response: {response.text}") from e

            if "access_token" not in response_data:
                raise Exception(f"No access token in response: {response_data}")

            return response_data["access_token"]
        except Exception as e:
            logger.error(f"Error generating access token: {str(e)}")
            raise

    def generate_password(self, timestamp: str) -> str:
        """Generate a password for the MPESA API transaction"""
        try:
            password = base64.b64encode(
                f"{self.MPESA_LNMO_SHORT_CODE}{self.MPESA_LNMO_PASS_KEY}{timestamp}".encode()
            ).decode()
            return password
        except Exception as e:
            logger.error(f"Error generating password: {str(e)}")
            raise
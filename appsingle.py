import base64
import requests
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Transaction, TransactionStatus, TransactionCategory, TransactionType, TransactionChannel, TransactionAggregator
from typing import Dict, Any
import os
import logging
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

class LNMORepository:
    MPESA_LNMO_CONSUMER_KEY = os.getenv("MPESA_LNMO_CONSUMER_KEY")
    MPESA_LNMO_CONSUMER_SECRET = os.getenv("MPESA_LNMO_CONSUMER_SECRET")
    MPESA_LNMO_ENVIRONMENT = os.getenv("MPESA_LNMO_ENVIRONMENT", "sandbox")
    MPESA_LNMO_PASS_KEY = os.getenv("MPESA_LNMO_PASS_KEY")
    MPESA_LNMO_SHORT_CODE = os.getenv("MPESA_LNMO_SHORT_CODE", "174379")
    MPESA_LNMO_CALLBACK_URL = os.getenv("MPESA_LNMO_CALLBACK_URL","https://d270-197-237-26-50.ngrok-free.app/ipn/daraja/lnmo/callback")
    MPESA_IPS = ["196.201.214.0/24"]  # Update with Safaricom IPs

    def __init__(self):
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
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            response_data = response.json()
            if "errorCode" in response_data:
                raise Exception(f"M-Pesa API error: {response_data.get('errorMessage')}")
            
            transaction = Transaction(
                _pid=data.get("pid", data["AccountReference"]),
                party_a=data["PhoneNumber"],
                party_b=self.MPESA_LNMO_SHORT_CODE,
                account_reference=data["AccountReference"],
                transaction_category=TransactionCategory.PURCHASE_ORDER,
                transaction_type=TransactionType.CREDIT,
                transaction_channel=TransactionChannel.LNMO,
                transaction_aggregator=TransactionAggregator.MPESA_KE,
                transaction_id=response_data.get("CheckoutRequestID"),
                transaction_amount=data["Amount"],
                transaction_code=None,
                transaction_timestamp=datetime.now(),
                transaction_details=f"Payment for order {data['AccountReference']}",
                _feedback=response_data,
                _status=TransactionStatus.PENDING,
                order_id=data.get("order_id"),
                user_id=data.get("user_id")
            )
            db.add(transaction)
            await db.commit()
            await db.refresh(transaction)
            logger.info(f"Transaction saved: ID={transaction.transaction_id}")
            return response_data
        except Exception as e:
            logger.error(f"Error initiating M-Pesa transaction: {str(e)}")
            raise

    async def callback(self, data: Dict[str, Any], request: Request, db: AsyncSession) -> Dict[str, Any]:
        if not self.verify_callback(request):
            logger.error(f"Invalid callback source: {request.client.host}")
            raise HTTPException(status_code=403, detail="Invalid callback source")
        
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
                if transaction.order:
                    transaction.order.status = OrderStatus.PROCESSING
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

    def verify_callback(self, request: Request) -> bool:
        return request.client.host in self.MPESA_IPS

    def generate_access_token(self) -> str:
        try:
            endpoint = f"https://{self.MPESA_LNMO_ENVIRONMENT}.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
            credentials = f"{self.MPESA_LNMO_CONSUMER_KEY}:{self.MPESA_LNMO_CONSUMER_SECRET}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers = {"Authorization": f"Basic {encoded_credentials}"}
            response = requests.get(endpoint, headers=headers, timeout=10)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            return response.json().get("access_token")
        except Exception as e:
            logger.error(f"Error generating access token: {str(e)}")
            raise

    def generate_password(self, timestamp: str) -> str:
        try:
            password = base64.b64encode(
                f"{self.MPESA_LNMO_SHORT_CODE}{self.MPESA_LNMO_PASS_KEY}{timestamp}".encode()
            ).decode()
            return password
        except Exception as e:
            logger.error(f"Error generating password: {str(e)}")
            raise
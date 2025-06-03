from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from models import TransactionStatus  # Import enum

class TransactionRequest(BaseModel):
    Amount: Decimal = Field(..., gt=0, description="Transaction amount")
    PhoneNumber: str = Field(..., regex=r"^\+254\d{9}$", description="Phone number in +254XXXXXXXXX format")
    AccountReference: str = Field(..., min_length=1, max_length=100, description="Account reference")

class QueryRequest(BaseModel):
    transaction_id: str = Field(..., description="Transaction ID to query")

class APIResponse(BaseModel):
    status: str
    message: str
    data: Dict[Any, Any] = {}

class TransactionResponse(BaseModel):
    id: int
    _pid: str
    party_a: str
    party_b: str
    account_reference: str
    transaction_amount: Decimal
    transaction_id: Optional[str]
    transaction_code: Optional[str]
    _status: TransactionStatus  # Use enum
    created_at: datetime
    
    class Config:
        from_attributes = True
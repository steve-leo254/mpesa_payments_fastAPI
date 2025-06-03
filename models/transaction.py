from sqlalchemy import Column, Integer, String, Numeric, DateTime, Text, JSON, ForeignKey, Enum
from sqlalchemy.sql import func
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import IntEnum

class TransactionStatus(Enum):
  PENDING = "PENDING"
  PROCESSING = "PROCESSING"
  PROCESSED = "PROCESSED"
  REJECTED = "REJECTED"
  ACCEPTED = "ACCEPTED"

class TransactionCategory(IntEnum):
    PURCHASE_ORDER = 0
    PAYOUT = 1

class TransactionType(IntEnum):
    DEBIT = 0
    CREDIT = 1

class TransactionChannel(IntEnum):
    C2B = 0
    LNMO = 1
    B2C = 2
    B2B = 3

class TransactionAggregator(IntEnum):
    MPESA_KE = 0
    PAYPAL_USD = 1


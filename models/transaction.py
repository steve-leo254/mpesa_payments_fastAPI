from sqlalchemy import Column, Integer, String, Numeric, DateTime, Text, JSON, ForeignKey, Enum
from sqlalchemy.sql import func
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import IntEnum

class TransactionStatus(IntEnum):
    PENDING = 0
    PROCESSING = 1
    PROCESSED = 2
    REJECTED = 3
    ACCEPTED = 4

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

# class Transaction(Base):
#     __tablename__ = 'transactions'
    
#     id = Column(Integer, primary_key=True, index=True)
#     _pid = Column(String(100), unique=True, nullable=False, index=True)
#     party_a = Column(String(100), nullable=False)
#     party_b = Column(String(100), nullable=False)
#     account_reference = Column(String(150), nullable=False)
#     transaction_category = Column(Enum(TransactionCategory), nullable=False)
#     transaction_type = Column(Enum(TransactionType), nullable=False)
#     transaction_channel = Column(Enum(TransactionChannel), nullable=False)
#     transaction_aggregator = Column(Enum(TransactionAggregator), nullable=False)
#     transaction_id = Column(String(100), unique=True, nullable=True, index=True)
#     transaction_amount = Column(Numeric(10, 2), nullable=False)
#     transaction_code = Column(String(100), unique=True, nullable=True)
#     transaction_timestamp = Column(DateTime, default=datetime.utcnow)
#     transaction_details = Column(Text, nullable=False)
#     _feedback = Column(JSON, nullable=False)
#     _status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING)
#     created_at = Column(DateTime, default=datetime.utcnow)
#     updated_at = Column(DateTime, onupdate=func.now)
#     user_id = Column(Integer, ForeignKey('users.id'))
#     order_id = Column(Integer, ForeignKey('orders.order_id'), nullable=True)
    
#     user = relationship("Users", back_populates="transactions")
#     order = relationship("Orders", back_populates="transactions")
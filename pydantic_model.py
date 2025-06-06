from pydantic import BaseModel, EmailStr,Field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from decimal import Decimal

class Role(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"

class OrderStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"

class UpdateOrderStatusRequest(BaseModel):
    status: OrderStatus

class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

class LoginUserRequest(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class CategoryBase(BaseModel):
    name: str
    description: Optional[str]

class CategoryResponse(CategoryBase):
    id: int

class ProductsBase(BaseModel):
    name: str
    cost: float
    price: float
    img_url: str
    stock_quantity: float
    barcode: int
    category_id: Optional[int]
    brand: Optional[str]
    description: Optional[str]

class ProductResponse(ProductsBase):
    id: int
    created_at: datetime
    user_id: int
    category: Optional[CategoryResponse]

class CartItem(BaseModel):
    id: int
    quantity: float

class CartPayload(BaseModel):
    cart: List[CartItem]
    address_id: Optional[int] = None
    delivery_fee: float = 0.0
    transaction_id: Optional[int] = None

class OrderDetailResponse(BaseModel):
    order_detail_id: int
    product_id: Optional[int]
    quantity: float
    total_price: float
    product: Optional[ProductResponse]

    class Config:
        from_attributes = True

class TokenVerifyRequest(BaseModel):
    token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    new_password: str

class TokenVerificationResponse(BaseModel):
    username: str
    tokenverification: str

class UpdateProduct(BaseModel):
    name: Optional[str]
    price: Optional[float]
    cost: Optional[float]
    img_url: Optional[str]
    stock_quantity: Optional[float]
    barcode: Optional[int]
    category_id: Optional[int]
    brand: Optional[str]
    description: Optional[str]

class PaginatedProductResponse(BaseModel):
    items: List[ProductResponse]
    total: int
    page: int
    limit: int
    pages: int

class ImageResponse(BaseModel):
    message: str
    img_url: str

class AddressBase(BaseModel):
    first_name: str
    last_name: str
    phone_number: str
    address: str
    additional_info: Optional[str]
    region: str
    city: str
    is_default: bool = False

class AddressCreate(AddressBase):
    pass

class AddressResponse(AddressBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class OrderResponse(BaseModel):
    order_id: int
    total: float
    datetime: datetime
    status: OrderStatus
    user_id: int
    delivery_fee: float
    completed_at: Optional[datetime]
    order_details: List[OrderDetailResponse]
    address: Optional[AddressResponse]

    class Config:
        from_attributes = True

class PaginatedOrderResponse(BaseModel):
    items: List[OrderResponse]
    total: int
    page: int
    limit: int
    pages: int

class InitiatePaymentRequest(BaseModel):
    order_id: int
    phone_number: str
    amount : float = Field(..., gt=0, description="Amount must be greater than 0")

class PaymentStatusResponse(BaseModel):
    status: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        from_attributes = True

class OrderWithUserResponse(BaseModel):
    order_id: int
    total: float
    datetime: datetime
    status: OrderStatus
    user_id: int
    delivery_fee: float
    completed_at: Optional[datetime]
    address: Optional[AddressResponse]
    user: UserResponse

    class Config:
        from_attributes = True

class PaginatedOrderWithUserResponse(BaseModel):
    items: List[OrderWithUserResponse]
    total: int
    page: int
    limit: int
    pages: int
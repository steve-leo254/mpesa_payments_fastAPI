from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Query, Request
from pydantic_model import (
    ProductsBase, CartPayload, CartItem, UpdateProduct, CategoryBase, CategoryResponse,
    ProductResponse, OrderResponse, OrderDetailResponse, Role, PaginatedProductResponse,
    ImageResponse, AddressCreate, AddressResponse, PaginatedOrderResponse, OrderStatus,
    InitiatePaymentRequest, PaymentStatusResponse, PaginatedOrderWithUserResponse, UpdateOrderStatusRequest
)
from typing import Annotated, List, Optional, Dict, Any
import models
from database import engine, db_dependency, Base
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, func, update, or_
from sqlalchemy.orm import joinedload
import auth
from auth import get_active_user
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import logging
from dotenv import load_dotenv
import os
from decimal import Decimal
from math import ceil
import uuid
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from repositories.lnmo_repository import LNMORepository

from contextlib import asynccontextmanager

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # Optional: Add shutdown logic if needed

app = FastAPI(lifespan=lifespan)
app.include_router(auth.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

user_dependency = Annotated[dict, Depends(get_active_user)]

def require_admin(user: user_dependency):
    if user.get("role") != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")

@app.post("/upload-image", response_model=ImageResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(user: user_dependency, file: UploadFile = File(...)):
    require_admin(user)
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image files are allowed")
        max_size = 5 * 1024 * 1024
        content = await file.read()
        if len(content) > max_size:
            raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in ["jpg", "jpeg", "png", "gif"]:
            raise HTTPException(status_code=400, detail="Unsupported image format")
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        file_path = UPLOAD_DIR / unique_filename
        with file_path.open("wb") as f:
            f.write(content)
        img_url = f"/uploads/{unique_filename}"
        logger.info(f"Image uploaded: {unique_filename} by user {user.get('id')}")
        return {"message": "Image uploaded successfully", "img_url": img_url}
    except Exception as e:
        logger.error(f"Error uploading image: {str(e)}")
        raise HTTPException(status_code=500, detail="Error uploading image")

@app.get("/public/products", response_model=PaginatedProductResponse, status_code=status.HTTP_200_OK)
async def browse_products(db: db_dependency, search: str = None, page: int = 1, limit: int = 10):
    try:
        skip = (page - 1) * limit
        query = select(models.Products).options(joinedload(models.Products.category))
        if search:
            query = query.filter(models.Products.name.ilike(f"%{search}%"))
            logger.info(f"Product search query: {search}")
        count_query = select(func.count()).select_from(models.Products)
        if search:
            count_query = count_query.filter(models.Products.name.ilike(f"%{search}%"))
        count_result = await db.execute(count_query)
        total = count_result.scalar()
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        products = result.scalars().all()
        total_pages = ceil(total / limit)
        return {
            "items": products,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": total_pages
        }
    except SQLAlchemyError as e:
        logger.error(f"Error fetching products: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching products")

@app.get("/public/products/{product_id}", response_model=ProductResponse, status_code=status.HTTP_200_OK)
async def get_product_by_id(product_id: int, db: db_dependency):
    try:
        result = await db.execute(
            select(models.Products).filter(models.Products.id == product_id).options(joinedload(models.Products.category))
        )
        product = result.scalars().first()
        if not product:
            logger.info(f"Product not found: ID {product_id}")
            raise HTTPException(status_code=404, detail="Product not found")
        return product
    except SQLAlchemyError as e:
        logger.error(f"Error fetching product by ID {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching product")

@app.get("/public/categories", response_model=List[CategoryResponse], status_code=status.HTTP_200_OK)
async def browse_categories(db: db_dependency):
    try:
        result = await db.execute(select(models.Categories))
        categories = result.scalars().all()
        return categories
    except SQLAlchemyError as e:
        logger.error(f"Error fetching categories: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching categories")

@app.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(user: user_dependency, db: db_dependency, category: CategoryBase):
    require_admin(user)
    try:
        db_category = models.Categories(**category.dict())
        db.add(db_category)
        await db.commit()
        await db.refresh(db_category)
        return db_category
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error creating category: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/products", status_code=status.HTTP_201_CREATED)
async def add_product(user: user_dependency, db: db_dependency, create_product: ProductsBase):
    require_admin(user)
    try:
        add_product = models.Products(**create_product.dict(), user_id=user.get("id"))
        db.add(add_product)
        await db.commit()
        await db.refresh(add_product)
        return {"message": "Product added successfully"}
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error adding product: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/products", response_model=PaginatedProductResponse, status_code=status.HTTP_200_OK)
async def fetch_products(user: user_dependency, db: db_dependency, search: str = None, page: int = 1, limit: int = 10):
    require_admin(user)
    try:
        skip = (page - 1) * limit
        query = select(models.Products).filter(models.Products.user_id == user.get("id")).options(joinedload(models.Products.category))
        if search:
            query = query.filter(models.Products.name.ilike(f"%{search}%"))
            logger.info(f"Admin product search query: {search}")
        count_query = select(func.count()).select_from(models.Products).filter(models.Products.user_id == user.get("id"))
        if search:
            count_query = count_query.filter(models.Products.name.ilike(f"%{search}%"))
        count_result = await db.execute(count_query)
        total = count_result.scalar()
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        products = result.scalars().all()
        total_pages = ceil(total / limit)
        return {
            "items": products,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": total_pages
        }
    except SQLAlchemyError as e:
        logger.error(f"Error fetching products: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching products")

@app.put("/update-product/{product_id}", status_code=status.HTTP_200_OK)
async def update_product(product_id: int, updated_data: UpdateProduct, user: user_dependency, db: db_dependency):
    require_admin(user)
    try:
        result = await db.execute(
            select(models.Products).filter(
                models.Products.id == product_id,
                models.Products.user_id == user.get("id")
            ).options(joinedload(models.Products.category))
        )
        product = result.scalars().first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        update_dict = updated_data.dict(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(product, key, value)
        await db.commit()
        await db.refresh(product)
        return {"message": "Product updated successfully"}
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error updating product: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-product/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(product_id: int, db: db_dependency, user: user_dependency):
    require_admin(user)
    try:
        result = await db.execute(
            select(models.Products).filter(
                models.Products.id == product_id,
                models.Products.user_id == user.get("id")
            )
        )
        product = result.scalars().first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        result = await db.execute(
            select(models.OrderDetails).filter(models.OrderDetails.product_id == product_id)
        )
        order_details = result.scalars().first()
        if order_details:
            raise HTTPException(status_code=400, detail="Cannot delete product with existing orders")
        await db.delete(product)
        await db.commit()
        return {"message": "Product deleted successfully"}
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error deleting product: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create_order", status_code=status.HTTP_201_CREATED)
async def create_order(db: db_dependency, user: user_dependency, order_payload: CartPayload):
    try:
        address_id = order_payload.address_id
        if address_id:
            stmt = select(models.Address).filter(
                models.Address.id == address_id,
                models.Address.user_id == user.get("id")
            )
            result = await db.execute(stmt)
            address = result.scalars().first()
            if not address:
                raise HTTPException(status_code=400, detail="Invalid address ID")

        delivery_fee = Decimal(str(order_payload.delivery_fee))
        new_order = models.Orders(
            user_id=user.get("id"),
            total=0,
            address_id=address_id,
            delivery_fee=delivery_fee
        )
        db.add(new_order)
        await db.commit()
        await db.refresh(new_order)

        total_cost = Decimal('0')
        for item in order_payload.cart:
            stmt = select(models.Products).filter_by(id=item.id)
            result = await db.execute(stmt)
            product = result.scalars().first()
            if not product:
                await db.rollback()
                raise HTTPException(status_code=404, detail=f"Product ID {item.id} not found")
            quantity = Decimal(str(item.quantity))
            if product.stock_quantity < quantity:
                await db.rollback()
                raise HTTPException(status_code=400, detail=f"Insufficient stock for product {product.name}")

            order_detail = models.OrderDetails(
                order_id=new_order.order_id,
                product_id=product.id,
                quantity=quantity,
                total_price=product.price * quantity,
            )
            total_cost += order_detail.total_price
            product.stock_quantity -= quantity
            db.add(order_detail)

        new_order.total = total_cost + new_order.delivery_fee
        await db.commit()

        logger.info(f"Order {new_order.order_id} created for user {user.get('id')}")
        return {
            "message": "Order created successfully",
            "order_id": new_order.order_id,
        }
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error creating order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        await db.rollback()
        logger.error(f"Invalid quantity value: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid quantity value")

@app.get("/orders", response_model=PaginatedOrderResponse, status_code=status.HTTP_200_OK)
async def fetch_orders(
    user: user_dependency,
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[OrderStatus] = None
):
    try:
        query = select(models.Orders).filter(models.Orders.user_id == user.get("id"))
        if status:
            query = query.filter(models.Orders.status == status)

        count_query = select(func.count()).select_from(models.Orders).filter(models.Orders.user_id == user.get("id"))
        if status:
            count_query = count_query.filter(models.Orders.status == status)
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        query = query.options(
            joinedload(models.Orders.user),
            joinedload(models.Orders.order_details).joinedload(models.OrderDetails.product).joinedload(models.Products.category),
            joinedload(models.Orders.address)
        ).offset(skip).limit(limit)

        result = await db.execute(query)
        orders = result.unique().scalars().all()

        page = (skip // limit) + 1
        pages = ceil(total / limit) if limit > 0 else 0
        return {
            "items": orders,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages
        }
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error fetching orders: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching orders")

@app.get("/orders/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
async def get_order_by_id(order_id: int, user: user_dependency, db: db_dependency):
    try:
        result = await db.execute(
            select(models.Orders).filter(
                models.Orders.order_id == order_id,
                models.Orders.user_id == user.get("id")
            ).options(
                joinedload(models.Orders.order_details).joinedload(models.OrderDetails.product).joinedload(models.Products.category),
                joinedload(models.Orders.address)
            )
        )
        order = result.scalars().first()
        if not order:
            logger.info(f"Order not found: ID {order_id} for user {user.get('id')}")
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except SQLAlchemyError as e:
        logger.error(f"Error fetching order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching order")

@app.get("/admin/orders/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
async def get_admin_order_by_id(order_id: int, user: user_dependency, db: db_dependency):
    require_admin(user)
    try:
        result = await db.execute(
            select(models.Orders).filter(models.Orders.order_id == order_id).options(
                joinedload(models.Orders.order_details).joinedload(models.OrderDetails.product).joinedload(models.Products.category),
                joinedload(models.Orders.address),
                joinedload(models.Orders.user)
            )
        )
        order = result.scalars().first()
        if not order:
            logger.info(f"Order not found: ID {order_id}")
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except SQLAlchemyError as e:
        logger.error(f"Error fetching order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching order")

@app.get("/dashboard", status_code=status.HTTP_200_OK)
async def dashboard(user: user_dependency, db: db_dependency):
    require_admin(user)
    try:
        id = user.get("id")
        today = datetime.utcnow().date()

        sales_query = (
            select(func.sum(models.OrderDetails.total_price))
            .join(models.Products)
            .filter(models.Products.user_id == id)
        )
        total_sales = (await db.execute(sales_query)).scalar() or 0

        products_query = select(func.count()).select_from(models.Products).filter(models.Products.user_id == id)
        total_products = (await db.execute(products_query)).scalar() or 0

        today_sales_query = (
            select(func.sum(models.OrderDetails.total_price))
            .join(models.Orders)
            .join(models.Products)
            .filter(models.Products.user_id == id, func.date(models.Orders.datetime) == today)
        )
        today_sale = (await db.execute(today_sales_query)).scalar() or 0

        return {
            "total_sales": float(total_sales),
            "total_products": total_products,
            "today_sale": float(today_sale),
        }
    except SQLAlchemyError as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching dashboard data")

@app.post("/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(user: user_dependency, db: db_dependency, address: AddressCreate):
    try:
        if address.is_default:
            stmt = (
                update(models.Address)
                .where(models.Address.user_id == user.get("id"), models.Address.is_default == True)
                .values(is_default=False)
            )
            await db.execute(stmt)

        db_address = models.Address(**address.dict(), user_id=user.get("id"))
        db.add(db_address)
        await db.commit()
        await db.refresh(db_address)
        logger.info(f"Address created for user {user.get('id')}: Address ID {db_address.id}")
        return db_address
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error creating address: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating address")

@app.get("/addresses", response_model=List[AddressResponse])
async def get_addresses(
    user: user_dependency,
    db: db_dependency,
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0)
):
    try:
        stmt = select(models.Address).where(models.Address.user_id == user.get("id")).limit(limit).offset(offset)
        result = await db.execute(stmt)
        addresses = result.scalars().all()
        if not addresses:
            logger.info(f"No addresses found for user {user.get('id')}")
            return []
        logger.info(f"Retrieved {len(addresses)} addresses for user {user.get('id')}")
        return addresses
    except SQLAlchemyError as e:
        logger.error(f"Error fetching addresses: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching addresses")

@app.delete("/addresses/{id}", status_code=status.HTTP_200_OK)
async def delete_address(address_id: int, user: user_dependency, db: db_dependency):
    try:
        result = await db.execute(
            select(models.Address).filter(
                models.Address.id == address_id,
                models.Address.user_id == user.get("id")
            )
        )
        address = result.scalars().first()
        if not address:
            logger.info(f"Address not found: ID {address_id} for user {user.get('id')}")
            raise HTTPException(status_code=404, detail="Address not found")

        order = await db.execute(select(models.Orders).filter(models.Orders.address_id == address_id))
        order = order.scalars().first()
        if order:
            logger.info(f"Cannot delete address {address_id}: used in order {order.order_id}")
            raise HTTPException(status_code=400, detail="Cannot delete address used in orders")

        await db.delete(address)
        await db.commit()
        logger.info(f"Address {address_id} deleted by user {user.get('id')}")
        return {"message": "Address deleted successfully"}
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Error deleting address {address_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error deleting address")

@app.get("/admin/orders", response_model=PaginatedOrderWithUserResponse, status_code=status.HTTP_200_OK)
async def fetch_all_orders(
    user: user_dependency,
    db: db_dependency,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[OrderStatus] = None,
    search: Optional[str] = None
):
    require_admin(user)
    try:
        query = select(models.Orders).join(models.Users, models.Orders.user_id == models.Users.id)
        if status:
            query = query.filter(models.Orders.status == status)
        if search:
            query = query.join(models.Address, models.Orders.address_id == models.Address.id, isouter=True).filter(
                or_(
                    models.Users.username.ilike(f"%{search}%"),
                    models.Address.first_name.ilike(f"%{search}%"),
                    models.Address.last_name.ilike(f"%{search}%")
                )
            )

        count_query = select(func.count()).select_from(models.Orders).join(models.Users, models.Orders.user_id == models.Users.id)
        if status:
            count_query = count_query.filter(models.Orders.status == status)
        if search:
            count_query = count_query.join(models.Address, models.Orders.address_id == models.Address.id, isouter=True).filter(
                or_(
                    models.Users.username.ilike(f"%{search}%"),
                    models.Address.first_name.ilike(f"%{search}%"),
                    models.Address.last_name.ilike(f"%{search}%")
                )
            )
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        query = query.options(joinedload(models.Orders.address), joinedload(models.Orders.user)).offset(skip).limit(limit)

        result = await db.execute(query)
        orders = result.unique().scalars().all()

        page = (skip // limit) + 1
        pages = ceil(total / limit) if limit > 0 else 0

        logger.info(f"Admin {user.get('id')} fetched {len(orders)} orders (page {page}, limit {limit})")
        return {
            "items": orders,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages
        }
    except SQLAlchemyError as e:
        logger.error(f"Error fetching all orders: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching orders")

@app.put("/update-order-status/{order_id}", status_code=status.HTTP_200_OK)
async def update_order_status(
    order_id: int,
    request: UpdateOrderStatusRequest,
    user: user_dependency,
    db: db_dependency
):
    try:
        require_admin(user)

        result = await db.execute(select(models.Orders).filter(models.Orders.order_id == order_id))
        order = result.scalars().first()

        if not order:
            logger.info(f"Order not found: ID {order_id}")
            raise HTTPException(status_code=404, detail="Order not found")

        logger.info(f"Setting order {order_id} status to: {request.status} (value: {request.status.value})")

        if request.status.value == "pending":
            order.status = models.OrderStatus.PENDING
        elif request.status.value == "delivered":
            order.status = models.OrderStatus.DELIVERED
        elif request.status.value == "cancelled":
            order.status = models.OrderStatus.CANCELLED
        else:
            raise HTTPException(status_code=400, detail=f"Invalid status: {request.status.value}")

        if request.status.value == "delivered":
            order.completed_at = func.now()
        elif order.completed_at and request.status.value != "delivered":
            order.completed_at = None

        await db.commit()
        await db.refresh(order)

        logger.info(f"Order {order_id} status updated to {request.status} by user {user.get('id')}")
        return {
            "message": f"Order status updated to {request.status.value}",
            "order_id": order_id,
            "new_status": request.status.value
        }
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"SQLAlchemy error updating order status for order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Database error updating order status")
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected error updating order status for order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error updating order status")


@app.post("/initiate_payment", status_code=status.HTTP_200_OK)
async def initiate_payment(request: InitiatePaymentRequest, user: user_dependency, db: db_dependency):
    try:
        # Validate amount early
        if request.amount != int(request.amount):
            raise HTTPException(status_code=400, detail="Amount must be a whole number")
        
        amount_int = int(request.amount)
        if amount_int < 1:
            raise HTTPException(status_code=400, detail="Amount must be at least 1 KES")
        if amount_int > 70000:
            raise HTTPException(status_code=400, detail="Amount cannot exceed 70,000 KES")

        result = await db.execute(
            select(models.Orders).filter(
                models.Orders.order_id == request.order_id,
                models.Orders.user_id == user.get("id")
            )
        )
        order = result.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Verify amount matches order total
        if amount_int != int(order.total):
            raise HTTPException(status_code=400, detail="Amount does not match order total")

        result = await db.execute(
            select(models.Transaction).filter(models.Transaction.order_id == request.order_id)
        )
        existing_transaction = result.scalars().first()
        if existing_transaction and existing_transaction._status == models.TransactionStatus.ACCEPTED:
            raise HTTPException(status_code=400, detail="Payment already accepted")

        data = {
            "Amount": amount_int,  # Use integer directly
            "PhoneNumber": request.phone_number,
            "AccountReference": str(request.order_id),
            "pid": str(uuid.uuid4()),
            "order_id": request.order_id,
            "user_id": user.get("id")
        }

        lnmo_repo = LNMORepository()
        response = await lnmo_repo.transact(data, db)

        return {"message": "Payment initiated", "CheckoutRequestID": response.get("CheckoutRequestID")}
    except Exception as e:
        logger.error(f"Error initiating payment: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Payment initiation failed: {str(e)}")
    
    

@app.post("/payment_callback", status_code=status.HTTP_200_OK)
async def payment_callback(callback_data: Dict[str, Any], request: Request, db: db_dependency):
    try:
        lnmo_repo = LNMORepository()
        response = await lnmo_repo.callback(callback_data, request, db)
        return {"message": "Callback processed", "response": response}
    except Exception as e:
        logger.error(f"Error processing callback: {str(e)}")
        raise HTTPException(status_code=500, detail="Callback processing failed")

@app.get("/check_payment_status/{order_id}", response_model=PaymentStatusResponse, status_code=status.HTTP_200_OK)
async def check_payment_status(order_id: int, user: user_dependency, db: db_dependency):
    try:
        result = await db.execute(
            select(models.Transaction).filter(
                models.Transaction.order_id == order_id,
                models.Transaction.user_id == user.get("id")
            ).order_by(models.Transaction.created_at.desc())
        )
        transaction = result.scalars().first()
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return PaymentStatusResponse(status=transaction._status.name)
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking payment status")





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
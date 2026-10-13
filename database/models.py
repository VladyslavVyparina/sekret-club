"""
Моделі бази даних
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserStatus(str, Enum):
    NOT_SUBSCRIBER = "not_subscriber"  # Ніколи не платив
    SUBSCRIBER = "subscriber"  # Активний підписник
    FORMER_SUBSCRIBER = "former_subscriber"  # Колишній підписник


class ContentType(str, Enum):
    COURSE = "course"
    STREAM = "stream"
    MATERIAL = "material"
    BOOK = "book"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=UserStatus.NOT_SUBSCRIBER.value)
    has_used_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    rec_token: Mapped[str | None] = mapped_column(String(500), nullable=True)  # WayForPay token
    order_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    subscriptions = relationship("Subscription", back_populates="user", order_by="Subscription.id.desc()")
    payments = relationship("Payment", back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="subscriptions")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_reference: Mapped[str] = mapped_column(String(100), index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="UAH")
    status: Mapped[str] = mapped_column(String(50))
    transaction_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    auth_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    card_pan: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rec_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="payments")


class PaymentFailure(Base):
    """Неуспішна оплата — для retry по розкладу Day 0, 2, 4, 7, 11, 14"""
    __tablename__ = "payment_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_reference: Mapped[str] = mapped_column(String(100), index=True)
    rec_token: Mapped[str] = mapped_column(String(500))
    first_failure_at: Mapped[datetime] = mapped_column(DateTime)
    retry_index: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Content(Base):
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("content.id"), nullable=True)
    content_type: Mapped[str] = mapped_column(String(50))  # course, stream, material, book
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Telegram file_id
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent = relationship("Content", remote_side=[id], back_populates="children", overlaps="children")
    children = relationship("Content", back_populates="parent", overlaps="parent")
    lessons = relationship("Lesson", back_populates="content", order_by="Lesson.sort_order")


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    content = relationship("Content", back_populates="lessons")


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    message_type: Mapped[str] = mapped_column(String(50))  # text, photo, video, document
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filter_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_recipients: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fail_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Прості налаштування (тарифи, тексти тощо)"""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Tariff(Base):
    """Тарифи підписки (назва + ціна, для інтеграції з WayForPay)"""
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # trial, standard, etc.
    name: Mapped[str] = mapped_column(String(255))
    price_grn: Mapped[int] = mapped_column(Integer)  # ціна в гривнях
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PayLink(Base):
    """Коротке посилання на оплату (щоб не світити token у URL)"""
    __tablename__ = "pay_links"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)  # випадковий код
    telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    tariff: Mapped[str] = mapped_column(String(20))  # trial | standard
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

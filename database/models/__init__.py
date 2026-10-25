"""Database schema for a single-barber booking application."""
from datetime import datetime, time, date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (BigInteger, Boolean, Identity, CheckConstraint, Date, DateTime,
                        ForeignKey, Integer, Numeric, String, Time, UniqueConstraint,
                        func, text)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, server_default=Identity())
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=Identity())
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    __table_args__ = (CheckConstraint("price >= 0", name="ck_services_price_nonnegative"),)


class WorkingHours(Base):
    __tablename__ = "working_hours"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=Identity())
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    ends_at: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    __table_args__ = (CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_working_hours_weekday"),
                      CheckConstraint("starts_at < ends_at", name="ck_working_hours_order"),)


class DayOff(Base):
    __tablename__ = "days_off"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=Identity())
    day: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'confirmed'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    user: Mapped[User] = relationship(User)
    service: Mapped[Service] = relationship(Service)
    __table_args__ = (CheckConstraint("ends_at = starts_at + interval '1 hour'", name="ck_bookings_60_minutes"),
                      CheckConstraint("price_snapshot >= 0", name="ck_bookings_price_nonnegative"),
                      CheckConstraint("status IN ('confirmed','completed','cancelled','no_show')", name="ck_bookings_status"),)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, server_default=Identity())
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payments_positive_amount"),
                      CheckConstraint("method IN ('cash','card')", name="ck_payments_method"),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, server_default=Identity())
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    __table_args__ = (UniqueConstraint("booking_id", "kind", name="uq_notifications_booking_kind"),
                      CheckConstraint("kind IN ('reminder_24h','reminder_2h')", name="ck_notifications_kind"),
                      CheckConstraint("status IN ('pending','sending','sent','failed','cancelled')", name="ck_notifications_status"),
                      CheckConstraint("attempts >= 0", name="ck_notifications_attempts"),)


class BarberProfile(Base):
    __tablename__ = "barber_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(String(500), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating"),)

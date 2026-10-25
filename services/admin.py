
"""Действия администратора с услугами, расписанием и записями."""

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import (
    Service,
    WorkingHours,
    DayOff,
    Booking,
    Payment,
    User,
)


class AdminError(ValueError):
    pass


def money(value: str) -> Decimal:
    try:
        amount = Decimal(value.strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise AdminError(
            "Введите цену числом, например 50 или 50.50."
        )

    if (
        not amount.is_finite()
        or amount < 0
        or amount.as_tuple().exponent < -2
        or amount > Decimal("9999999999.99")
    ):
        raise AdminError(
            "Цена должна быть неотрицательной, "
            "максимум 2 знака после запятой."
        )

    return amount


class AdminService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
    ):
        self.sessions = sessions

    async def services(self):
        async with self.sessions() as session:
            return (
                await session.scalars(
                    select(Service).order_by(Service.id)
                )
            ).all()

    async def add_service(self, name: str, price: str):
        name = name.strip()

        if not 1 <= len(name) <= 120:
            raise AdminError(
                "Название должно быть от 1 до 120 символов."
            )

        cost = money(price)

        async with self.sessions() as session, session.begin():
            if await session.scalar(
                select(Service.id).where(Service.name == name)
            ):
                raise AdminError(
                    "Услуга с таким названием уже существует."
                )

            session.add(
                Service(
                    name=name,
                    price=cost,
                    is_active=True,
                )
            )

    async def update_service(
        self,
        service_id: int,
        *,
        name: str | None = None,
        price: str | None = None,
        active: bool | None = None,
    ):
        """Редактировать или скрыть услугу без удаления истории."""

        async with self.sessions() as session, session.begin():
            service = await session.get(
                Service,
                service_id,
                with_for_update=True,
            )

            if not service or service.name == "Запись к мастеру":
                raise AdminError(
                    "Услуга не найдена или её нельзя изменить."
                )

            if name is not None:
                name = name.strip()

                if (
                    not 2 <= len(name) <= 120
                    or name == "Запись к мастеру"
                ):
                    raise AdminError(
                        "Название услуги должно содержать "
                        "от 2 до 120 символов."
                    )

                other = await session.scalar(
                    select(Service.id).where(
                        Service.name == name,
                        Service.id != service_id,
                    )
                )

                if other is not None:
                    raise AdminError(
                        "Услуга с таким названием уже существует."
                    )

                service.name = name

            if price is not None:
                service.price = money(price)

            if active is not None:
                service.is_active = active

    async def hours(self):
        async with self.sessions() as session:
            return (
                await session.scalars(
                    select(WorkingHours).order_by(
                        WorkingHours.weekday,
                        WorkingHours.starts_at,
                    )
                )
            ).all()

    async def set_hours(
        self,
        weekday: int,
        start: time | None,
        end: time | None,
    ):
        if weekday not in range(7):
            raise AdminError("Неверный день недели.")

        if (
            (start is None) != (end is None)
            or (
                start
                and (
                    start >= end
                    or (
                        datetime.combine(date.today(), end)
                        - datetime.combine(date.today(), start)
                    ).total_seconds() < 3600
                )
            )
        ):
            raise AdminError(
                "Укажите корректный интервал минимум на один час."
            )

        async with self.sessions() as session, session.begin():
            await session.execute(
                delete(WorkingHours).where(
                    WorkingHours.weekday == weekday
                )
            )

            if start:
                session.add(
                    WorkingHours(
                        weekday=weekday,
                        starts_at=start,
                        ends_at=end,
                    )
                )

        # Существующие записи не удаляются.

    async def days_off(self):
        async with self.sessions() as session:
            return (
                await session.scalars(
                    select(DayOff).order_by(DayOff.day).limit(80)
                )
            ).all()

    async def set_day_off(
        self,
        day: date,
        enabled: bool,
    ):
        async with self.sessions() as session, session.begin():
            existing = await session.scalar(
                select(DayOff).where(DayOff.day == day)
            )

            if enabled and not existing:
                session.add(
                    DayOff(
                        day=day,
                        reason="Выходной",
                    )
                )

            if not enabled and existing:
                await session.delete(existing)

    async def bookings(self, limit: int = 30):
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(
                        Booking,
                        User.name,
                        User.phone,
                        Service.name,
                    )
                    .join(
                        User,
                        Booking.user_id == User.id,
                    )
                    .join(
                        Service,
                        Booking.service_id == Service.id,
                    )
                    .order_by(Booking.starts_at.desc())
                    .limit(limit)
                )
            ).all()

    async def booking_detail(self, booking_id: UUID):
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(
                        Booking,
                        User.name,
                        User.phone,
                        Service.name,
                    )
                    .join(
                        User,
                        Booking.user_id == User.id,
                    )
                    .join(
                        Service,
                        Booking.service_id == Service.id,
                    )
                    .where(Booking.id == booking_id)
                )
            ).first()

    async def set_status(
        self,
        booking_id: UUID,
        status: str,
    ):
        if status not in ("completed", "no_show", "cancelled"):
            raise AdminError("Недопустимый статус.")

        async with self.sessions() as session, session.begin():
            booking = await session.get(
                Booking,
                booking_id,
                with_for_update=True,
            )

            if not booking:
                raise AdminError("Запись не найдена.")

            if booking.status != "confirmed":
                raise AdminError("Запись уже обработана.")

            if (
                status in ("completed", "no_show")
                and booking.starts_at > datetime.now(timezone.utc)
            ):
                raise AdminError(
                    "Нельзя отметить будущий визит "
                    "завершённым или неявкой."
                )

            booking.status = status

    async def payment(
        self,
        booking_id: UUID,
        method: str,
    ):
        if method not in ("cash", "card"):
            raise AdminError("Недопустимый способ оплаты.")

        async with self.sessions() as session, session.begin():
            booking = await session.get(
                Booking,
                booking_id,
                with_for_update=True,
            )

            if not booking or booking.status != "completed":
                raise AdminError(
                    "Оплату можно отметить только "
                    "после завершения визита."
                )

            existing = await session.scalar(
                select(Payment.id).where(
                    Payment.booking_id == booking_id
                )
            )

            if existing:
                raise AdminError("Оплата уже отмечена.")

            session.add(
                Payment(
                    booking_id=booking_id,
                    amount=booking.price_snapshot,
                    method=method,
                )
            )

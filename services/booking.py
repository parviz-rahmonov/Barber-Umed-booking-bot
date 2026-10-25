"""Stage 3 booking rules; no Telegram UI here.

One barber; all sessions last 60 minutes. PostgreSQL exclusion constraint
is the final authority during simultaneous bookings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from database.models import Booking, DayOff, Service, User, WorkingHours, Notification

DURATION = timedelta(hours=1)
HORIZON = timedelta(days=30)
MIN_NOTICE = timedelta(hours=1)
CHANGE_NOTICE = timedelta(hours=2)
BLOCKING_STATUSES = ('confirmed', 'completed', 'no_show')
UTC = timezone.utc


class BookingError(Exception):
    """User-facing domain error; never expose raw SQL errors to clients."""


class SlotUnavailable(BookingError):
    pass


class BookingNotFound(BookingError):
    pass


class BookingForbidden(BookingError):
    pass


@dataclass(frozen=True)
class Slot:
    starts_at: datetime  # aware UTC
    ends_at: datetime    # aware UTC


def _aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('Time must have an explicit UTC offset')
    return dt.astimezone(UTC)


def _local_candidate(day: date, at: time, tz: ZoneInfo) -> datetime | None:
    """Reject nonexistent or ambiguous wall times (DST), instead of double-booking."""
    naive = datetime.combine(day, at)
    d0 = naive.replace(tzinfo=tz, fold=0)
    d1 = naive.replace(tzinfo=tz, fold=1)
    if d0.utcoffset() != d1.utcoffset():
        return None
    utc = d0.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return utc


def build_day_slots(day: date, ranges: list[tuple[time, time]], tz_name: str) -> list[Slot]:
    """Hourly start grid relative to opening time, no overrun into breaks."""
    tz = ZoneInfo(tz_name)
    output: list[Slot] = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        cursor = datetime.combine(day, start)
        last = datetime.combine(day, end)
        while cursor + DURATION <= last:
            utc = _local_candidate(day, cursor.time(), tz)
            if utc is not None:
                end_utc = utc + DURATION
                # Do not allow slots that traverse a clock jump or extend past closing.
                end_local = end_utc.astimezone(tz)
                if end_local.date() == day and end_local.replace(tzinfo=None) <= last:
                    output.append(Slot(utc, end_utc))
            cursor += DURATION
    return sorted(set(output), key=lambda s: s.starts_at)


class BookingService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], timezone_name: str = 'Asia/Dushanbe'):
        self.sessions = sessions
        self.tz_name = timezone_name
        self.tz = ZoneInfo(timezone_name)

    async def _slots(self, session: AsyncSession, day: date) -> list[Slot]:
        off = await session.scalar(select(DayOff.id).where(DayOff.day == day))
        if off is not None:
            return []
        rows = (await session.execute(select(WorkingHours.starts_at, WorkingHours.ends_at)
                                      .where(WorkingHours.weekday == day.weekday()))).all()
        return build_day_slots(day, [(start, end) for start, end in rows], self.tz_name)

    async def available_slots(self, day: date, *, now: datetime | None = None) -> list[Slot]:
        now_utc = _aware_utc(now or datetime.now(UTC))
        now_local = now_utc.astimezone(self.tz)
        if day < now_local.date() or day > now_local.date() + HORIZON:
            return []
        async with self.sessions() as session:
            slots = [s for s in await self._slots(session, day)
                     if s.starts_at >= now_utc + MIN_NOTICE]
            if not slots:
                return []
            first = slots[0].starts_at
            last = slots[-1].ends_at
            busy = (await session.execute(select(Booking.starts_at, Booking.ends_at)
                    .where(Booking.status.in_(BLOCKING_STATUSES),
                           Booking.starts_at < last, Booking.ends_at > first))).all()
            return [s for s in slots if all(s.ends_at <= bstart or s.starts_at >= bend
                                           for bstart, bend in busy)]

    async def _validate_slot(self, session: AsyncSession, starts_at: datetime,
                             now_utc: datetime, *, for_change: bool = False) -> None:
        local_day = starts_at.astimezone(self.tz).date()
        now_day = now_utc.astimezone(self.tz).date()
        if local_day < now_day or local_day > now_day + HORIZON:
            raise SlotUnavailable('Дата вне доступного периода (30 дней).')
        if starts_at < now_utc + MIN_NOTICE:
            raise SlotUnavailable('Нельзя записаться менее чем за час до начала.')
        slots = await self._slots(session, local_day)
        if starts_at not in {slot.starts_at for slot in slots}:
            raise SlotUnavailable('Это время отсутствует в рабочем графике.')

    async def create(self, *, user_id: int, service_id: int, starts_at: datetime,
                     now: datetime | None = None) -> UUID:
        starts_at = _aware_utc(starts_at)
        now_utc = _aware_utc(now or datetime.now(UTC))
        try:
            async with self.sessions() as session:
                async with session.begin():
                    await self._validate_slot(session, starts_at, now_utc)
                    user = await session.get(User, user_id)
                    svc = await session.get(Service, service_id)
                    if user is None:
                        raise BookingError('Клиент не найден.')
                    if svc is None or not svc.is_active:
                        raise BookingError('Услуга недоступна.')
                    record = Booking(user_id=user_id, service_id=service_id,
                                     starts_at=starts_at, ends_at=starts_at + DURATION,
                                     price_snapshot=svc.price, status='confirmed')
                    session.add(record)
                    await session.flush()  # PostgreSQL exclusion constraint arbitrates races
                    booking_id = record.id
            return booking_id
        except IntegrityError as exc:
            if _is_overlap(exc):
                raise SlotUnavailable('Время уже занято. Выберите другое.') from exc
            raise

    async def cancel(self, booking_id: UUID, *, user_id: int | None = None,
                     now: datetime | None = None, admin: bool = False) -> None:
        now_utc = _aware_utc(now or datetime.now(UTC))
        async with self.sessions() as session:
            async with session.begin():
                record = await session.get(Booking, booking_id, with_for_update=True)
                if record is None:
                    raise BookingNotFound('Запись не найдена.')
                if not admin and (user_id is None or record.user_id != user_id):
                    raise BookingForbidden('Нет доступа к записи.')
                if record.status != 'confirmed':
                    raise BookingError('Эту запись уже нельзя отменить.')
                if not admin and record.starts_at < now_utc + CHANGE_NOTICE:
                    raise BookingError('Отмена возможна не позднее чем за 2 часа.')
                record.status = 'cancelled'
                await _cancel_reminders(session, record.id)

    
    async def reschedule(
        self,
        booking_id: UUID,
        starts_at: datetime,
        *,
        user_id: int | None = None,
        now: datetime | None = None,
        admin: bool = False,
    ) -> None:
        """Перенос записи клиентом или администратором."""

        starts_at = _aware_utc(starts_at)
        now_utc = _aware_utc(now or datetime.now(UTC))

        try:
            async with self.sessions() as session:
                async with session.begin():
                    record = await session.get(
                        Booking,
                        booking_id,
                        with_for_update=True,
                    )

                    if record is None:
                        raise BookingNotFound(
                            "Запись не найдена."
                        )

                    # Клиент может переносить только свою запись.
                    # Администратор может переносить любую.
                    if not admin and (
                        user_id is None
                        or record.user_id != user_id
                    ):
                        raise BookingForbidden(
                            "Нет доступа к записи."
                        )

                    if record.status != "confirmed":
                        raise BookingError(
                            "Перенос этой записи невозможен."
                        )

                    # Для клиента действует ограничение 2 часа.
                    # Администратор может переносить запись
                    # независимо от времени её начала.
                    if (
                        not admin
                        and record.starts_at
                        < now_utc + CHANGE_NOTICE
                    ):
                        raise BookingError(
                            "Перенос возможен не позднее "
                            "чем за 2 часа."
                        )

                    # Проверяем рабочий график и новую дату.
                    await self._validate_slot(
                        session,
                        starts_at,
                        now_utc,
                    )

                    # Обновляем время записи.
                    record.starts_at = starts_at
                    record.ends_at = starts_at + DURATION

                    # Удаляем старые напоминания, если они есть.
                    await _cancel_reminders(
                        session,
                        record.id,
                    )

                    await session.flush()

        except IntegrityError as exc:
            if _is_overlap(exc):
                raise SlotUnavailable(
                    "Новое время уже занято. "
                    "Старая запись сохранена."
                ) from exc

            raise


def _is_overlap(exc: IntegrityError) -> bool:
    orig = exc.orig
    # asyncpg may wrap the underlying error in a DBAPI adapter.
    code = getattr(orig, 'sqlstate', None) or getattr(orig, 'pgcode', None)
    cause = getattr(orig, '__cause__', None)
    code = code or getattr(cause, 'sqlstate', None)
    return code == '23P01'


def _schedule_reminders(session: AsyncSession, booking: Booking) -> None:
    """Queue reminders in the same transaction as an appointment mutation."""
    for kind, delta in (("reminder_24h", timedelta(hours=24)),
                        ("reminder_2h", timedelta(hours=2))):
        session.add(Notification(booking_id=booking.id, kind=kind,
                                 scheduled_at=booking.starts_at - delta,
                                 status="pending", attempts=0))


async def _cancel_reminders(session: AsyncSession, booking_id: UUID) -> None:
    from sqlalchemy import delete
    await session.execute(delete(Notification).where(Notification.booking_id == booking_id))

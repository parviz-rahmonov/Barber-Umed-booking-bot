
"""Фоновая отправка напоминаний о записи."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from database.models import Booking, Notification, Service, User


logger = logging.getLogger(__name__)
UTC = timezone.utc


class ReminderWorker:
    def __init__(self, sessions, timezone_name="Asia/Dushanbe"):
        self.sessions = sessions
        self.tz = ZoneInfo(timezone_name)

    async def process_one(self, bot: Bot) -> bool:
        now = datetime.now(UTC)

        async with self.sessions() as session:
            async with session.begin():
                notification = await session.scalar(
                    select(Notification)
                    .where(
                        Notification.status == "pending",
                        Notification.scheduled_at <= now,
                    )
                    .order_by(
                        Notification.scheduled_at,
                        Notification.id,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )

                if notification is None:
                    return False

                booking = await session.get(
                    Booking,
                    notification.booking_id,
                )

                if (
                    booking is None
                    or booking.status != "confirmed"
                    or booking.starts_at <= now
                ):
                    notification.status = "cancelled"
                    return True

                user = await session.get(User, booking.user_id)
                service = await session.get(
                    Service,
                    booking.service_id,
                )

                if user is None or service is None:
                    notification.status = "failed"
                    return True

                local_time = booking.starts_at.astimezone(self.tz)

                period = (
                    "24 часа"
                    if notification.kind == "reminder_24h"
                    else "2 часа"
                )

                text = (
                    "💈 Напоминание Barber Umed\n\n"
                    f"⏰ До вашей записи осталось {period}.\n"
                    f"✂️ Услуга: {escape(service.name)}\n"
                    f"📅 Дата: {local_time:%d.%m.%Y}\n"
                    f"🕒 Время: {local_time:%H:%M}\n\n"
                    "Ждём вас!"
                )

                try:
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=text,
                    )
                except TelegramAPIError:
                    notification.attempts += 1

                    if notification.attempts >= 3:
                        notification.status = "failed"
                    else:
                        notification.scheduled_at = (
                            datetime.now(UTC)
                            + timedelta(minutes=1)
                        )

                    logger.exception(
                        "Не удалось отправить напоминание %s",
                        notification.id,
                    )
                else:
                    notification.status = "sent"
                    notification.sent_at = datetime.now(UTC)

                    logger.info(
                        "Напоминание %s отправлено",
                        notification.id,
                    )

                return True

    async def run(self, bot: Bot) -> None:
        logger.info("Служба напоминаний запущена")

        try:
            while True:
                try:
                    # Обрабатываем накопившуюся очередь.
                    processed = await self.process_one(bot)

                    if not processed:
                        await asyncio.sleep(30)

                except asyncio.CancelledError:
                    raise

                except Exception:
                    logger.exception(
                        "Ошибка службы напоминаний"
                    )
                    await asyncio.sleep(30)
        finally:
            logger.info("Служба напоминаний остановлена")

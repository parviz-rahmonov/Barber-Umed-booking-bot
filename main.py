"""aiogram polling entry point."""
import asyncio
import logging
import sys

from contextlib import suppress
from services.reminders import ReminderWorker
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers.admin.start import router as admin_router
from bot.handlers.client.start import router as client_router
from bot.handlers.client.info import router as info_router
from bot.handlers.client.reviews import router as review_router
from bot.handlers.admin.extras import router as admin_extras_router
from bot.handlers.client.booking import router as booking_router
from database.session import create_engine, create_session_factory
from services.booking import BookingService
from services.admin import AdminService
from config import Settings


def create_dispatcher(admin_id: int) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(admin_router)
    dispatcher.include_router(client_router)
    dispatcher.include_router(info_router)
    dispatcher.include_router(review_router)
    dispatcher.include_router(admin_extras_router)
    dispatcher.include_router(booking_router)
    # Dependency injection for all handlers.
    dispatcher["admin_id"] = admin_id
    return dispatcher


async def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("barber_bot")
    dispatcher = create_dispatcher(settings.admin_id)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    dispatcher["booking_service"] = BookingService(sessions, settings.timezone)
    dispatcher["admin_service"] = AdminService(sessions)
    logger.info("Barber Umed V2.0 starting")
    async with Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        reminder_worker = ReminderWorker(sessions, settings.timezone)
        asyncio.create_task(reminder_worker.run(bot))
        reminder_worker = ReminderWorker(
    sessions,
    settings.timezone,
    )
    reminder_task = None

    try:
        await bot.delete_webhook(drop_pending_updates=False)

        reminder_task = asyncio.create_task(
        reminder_worker.run(bot)
        )

        await dispatcher.start_polling(
        bot,
        allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        if reminder_task is not None:
            reminder_task.cancel()
  
            with suppress(asyncio.CancelledError):
               await reminder_task

        await engine.dispose()



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("barber_bot").info("Bot stopped")

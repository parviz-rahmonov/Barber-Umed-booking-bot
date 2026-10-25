"""Публичные услуги и профиль мастера."""
from html import escape
from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select
from bot.localization import BTN_PRICES, BTN_BARBER
from database.models import Service, BarberProfile
from services.booking import BookingService

router = Router(name="client_info")

@router.message(F.text == BTN_PRICES)
async def show_prices(m: Message, booking_service: BookingService):
    async with booking_service.sessions() as session:
        rows = (await session.scalars(select(Service).where(Service.is_active.is_(True), Service.name != 'Запись к мастеру').order_by(Service.name))).all()
    lines = ["✂️ Услуги и цены"]
    lines.extend(f"• {escape(s.name)}: {s.price} сомони" for s in rows)
    await m.answer("\n".join(lines) if rows else "✂️ Услуг пока нет.")

@router.message(F.text == BTN_BARBER)
async def show_profile(m: Message, booking_service: BookingService):
    async with booking_service.sessions() as session:
        profile = await session.get(BarberProfile, 1)
    if not profile:
        await m.answer('💈 Информация о мастере пока не заполнена.')
        return
    await m.answer(f'💈 Мастер: {escape(profile.name)}\n📞 Телефон: {escape(profile.phone)}\n📍 Адрес: {escape(profile.address)}')

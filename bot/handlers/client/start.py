"""Главное меню: единые подписи V2."""
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from bot.localization import BTN_BOOK, BTN_MINE, BTN_PRICES, BTN_BARBER, BTN_REVIEWS

router = Router(name="client_start")
MENU = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MINE)],
    [KeyboardButton(text=BTN_PRICES), KeyboardButton(text=BTN_BARBER)],
    [KeyboardButton(text=BTN_REVIEWS)],
], resize_keyboard=True)

@router.message(CommandStart())
async def client_start(message: Message) -> None:
    await message.answer("💈 Добро пожаловать в Barber Umed! Выберите действие:", reply_markup=MENU)

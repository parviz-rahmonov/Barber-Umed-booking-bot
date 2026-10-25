"""Русские подписи интерфейса; значения в базе данных не меняются."""

from datetime import date

DAYS_FULL = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)

STATUSES = {
    "confirmed": "Подтверждена",
    "completed": "Завершена",
    "cancelled": "Отменена",
    "no_show": "Клиент не пришёл",
}

PAYMENT_METHODS = {
    "cash": "Наличные",
    "card": "Карта",
}


def russian_date_short(day: date) -> str:
    return f"{day:%d.%m} — {DAYS_FULL[day.weekday()]}"


def booking_status(value: str) -> str:
    return STATUSES.get(value, "Неизвестный статус")


BTN_BOOK = "📅 Записаться"
BTN_MINE = "📋 Мои записи"
BTN_PRICES = "✂️ Услуги и цены"
BTN_BARBER = "💈 О мастере"
BTN_REVIEWS = "⭐ Отзывы"

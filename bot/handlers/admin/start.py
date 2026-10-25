
"""Панель владельца: график, просмотр, отмена и перенос записей."""

import logging
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.localization import booking_status, russian_date_short
from database.models import Booking, User
from services.admin import AdminError, AdminService
from services.booking import BookingError, BookingService


router = Router(name="admin")
logger = logging.getLogger(__name__)

DAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


class AdminForm(StatesGroup):
    working_hours = State()
    day_off = State()


def allowed(user, admin_id):
    return user is not None and user.id == admin_id


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=action,
                )
                for label, action in row
            ]
            for row in rows
        ]
    )


def menu():
    return kb([
        [
            ("🗓 Расписание", "a:schedule"),
            ("📋 Записи", "a:bookings"),
        ],
        [("✂️ Услуги и цены", "v:services"), ("💈 О мастере", "v:profile")],
        [("⭐ Отзывы", "v:reviews")],
    ])


def move_calendar(page, tz):
    today = datetime.now(tz).date()

    days = [
        today + timedelta(days=i)
        for i in range(
            page * 7,
            min(page * 7 + 7, 31),
        )
    ]

    rows = [
        [
            (
                russian_date_short(day),
                f"a:move_day:{day.isoformat()}",
            )
        ]
        for day in days
    ]

    nav = []

    if page > 0:
        nav.append((
            "◀ Назад",
            f"a:move_cal:{page - 1}",
        ))

    if page < 4:
        nav.append((
            "Вперёд ▶",
            f"a:move_cal:{page + 1}",
        ))

    if nav:
        rows.append(nav)

    rows.append([
        ("Отмена переноса", "a:move_stop")
    ])

    return kb(rows)


async def notify_client(
    bot: Bot,
    booking_service: BookingService,
    booking_id: UUID,
    text: str,
) -> None:
    """Ошибка уведомления не отменяет изменение записи."""

    async with booking_service.sessions() as session:
        booking = await session.get(Booking, booking_id)

        user = (
            await session.get(User, booking.user_id)
            if booking
            else None
        )

    if user is None:
        logger.warning(
            "Не найден клиент для записи %s",
            booking_id,
        )
        return

    try:
        await bot.send_message(
            user.telegram_id,
            text,
        )
    except TelegramAPIError:
        logger.exception(
            "Не удалось уведомить клиента о записи %s",
            booking_id,
        )


@router.message(Command("admin"))
async def admin_start(
    message: Message,
    admin_id: int,
    state: FSMContext,
):
    if not allowed(message.from_user, admin_id):
        await message.answer("Нет доступа.")
        return

    await state.clear()

    await message.answer(
        "Панель владельца Barber Umed:",
        reply_markup=menu(),
    )


@router.callback_query(F.data.startswith("a:"))
async def actions(
    q: CallbackQuery,
    admin_id: int,
    admin_service: AdminService,
    state: FSMContext,
    booking_service: BookingService,
    bot: Bot,
):
    if not allowed(q.from_user, admin_id):
        await q.answer(
            "Нет доступа.",
            show_alert=True,
        )
        return

    parts = (q.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    await q.answer()

    if not q.message:
        return

    try:
        # Главное меню
        if action == "menu":
            await state.clear()

            await q.message.answer(
                "Панель владельца:",
                reply_markup=menu(),
            )

        # Просмотр расписания
        elif action == "schedule":
            hours = await admin_service.hours()
            offs = await admin_service.days_off()

            detail = "\n".join(
                f"{DAYS[i]}: " + (
                    ", ".join(
                        f"{r.starts_at:%H:%M}-{r.ends_at:%H:%M}"
                        for r in hours
                        if r.weekday == i
                    )
                    or "выходной"
                )
                for i in range(7)
            )

            detail += "\nВыходные по датам: " + (
                ", ".join(str(x.day) for x in offs)
                or "нет"
            )

            buttons = [
                [(DAYS[i], f"a:weekday:{i}")]
                for i in range(7)
            ]

            buttons += [
                [
                    (
                        "Изменить выходной по дате",
                        "a:dayoff",
                    )
                ],
                [("Назад", "a:menu")],
            ]

            await q.message.answer(
                detail,
                reply_markup=kb(buttons),
            )

        # Изменение рабочих часов
        elif action == "weekday":
            i = int(parts[2])

            if i not in range(7):
                raise AdminError(
                    "Неверный день недели."
                )

            await state.set_state(
                AdminForm.working_hours
            )

            await state.update_data(weekday=i)

            await q.message.answer(
                f"{DAYS[i]}: введите часы, "
                "например 09:00-18:00, "
                "или «выходной». "
                "Существующие записи сохранятся."
            )

        # Изменение выходного
        elif action == "dayoff":
            await state.set_state(
                AdminForm.day_off
            )

            await q.message.answer(
                "Введите дату ГГГГ-ММ-ДД, "
                "например 2026-10-26. "
                "Повторный ввод снимет выходной."
            )

        # Список записей
        elif action == "bookings":
            rows = await admin_service.bookings()

            if not rows:
                await q.message.answer(
                    "Записей пока нет.",
                    reply_markup=menu(),
                )
                return

            for b, name, phone, _svc in rows:
                local = b.starts_at.astimezone(
                    booking_service.tz
                )

                await q.message.answer(
                    f"{local:%d.%m.%Y %H:%M} · "
                    f"{escape(name)} · "
                    f"{booking_status(b.status)}",
                    reply_markup=kb([
                        [
                            (
                                "Подробнее",
                                f"a:booking:{b.id}",
                            )
                        ]
                    ]),
                )

        # Подробности записи
        elif action == "booking":
            bid = UUID(parts[2])

            row = await admin_service.booking_detail(
                bid
            )

            if not row:
                raise AdminError(
                    "Запись не найдена."
                )

            b, name, phone, _svc = row

            local = b.starts_at.astimezone(
                booking_service.tz
            )

            buttons = []

            if b.status == "confirmed":
                buttons += [
                    [
                        (
                            "Перенести запись",
                            f"a:move:{bid}",
                        )
                    ],
                    [
                        (
                            "Отменить запись",
                            f"a:cancel:{bid}",
                        )
                    ],
                ]

            if b.status == "confirmed" and b.starts_at <= datetime.now(timezone.utc):
                buttons.append([("✅ Завершить посещение", f"v:complete:{bid}")])

            buttons.append([
                (
                    "К списку записей",
                    "a:bookings",
                )
            ])

            await q.message.answer(
                f"Имя: {escape(name)}\n"
                f"Телефон: {escape(phone or 'не указан')}\n"
                f"Дата и время: "
                f"{local:%d.%m.%Y %H:%M}\n"
                f"Статус: {booking_status(b.status)}",
                reply_markup=kb(buttons),
            )

        # Запрос подтверждения отмены
        elif action == "cancel":
            bid = UUID(parts[2])

            row = await admin_service.booking_detail(
                bid
            )

            if not row or row[0].status != "confirmed":
                raise AdminError(
                    "Запись не найдена или уже обработана."
                )

            await q.message.answer(
                "Точно отменить запись клиента?",
                reply_markup=kb([
                    [
                        (
                            "Да, отменить",
                            f"a:cancel_confirm:{bid}",
                        )
                    ],
                    [
                        (
                            "Нет, вернуться",
                            f"a:booking:{bid}",
                        )
                    ],
                ]),
            )

        # Подтверждение отмены
        elif action == "cancel_confirm":
            bid = UUID(parts[2])

            await booking_service.cancel(
                bid,
                admin=True,
            )

            await q.message.answer(
                "Запись отменена. "
                "Время снова свободно.",
                reply_markup=menu(),
            )

            await notify_client(
                bot,
                booking_service,
                bid,
                "❌ Ваша запись в Barber Umed "
                "отменена администратором.",
            )

        # Начало переноса
        elif action == "move":
            bid = UUID(parts[2])

            row = await admin_service.booking_detail(
                bid
            )

            if not row or row[0].status != "confirmed":
                raise AdminError(
                    "Перенос этой записи недоступен."
                )

            await state.clear()

            await state.update_data(
                admin_move_booking_id=str(bid)
            )

            await q.message.answer(
                "Выберите новую дату:",
                reply_markup=move_calendar(
                    0,
                    booking_service.tz,
                ),
            )

        # Страницы календаря
        elif action == "move_cal":
            data = await state.get_data()

            if "admin_move_booking_id" not in data:
                raise AdminError(
                    "Начните перенос заново "
                    "через список записей."
                )

            page = int(parts[2])

            if page not in range(5):
                raise AdminError(
                    "Неверная страница календаря."
                )

            await q.message.answer(
                "Выберите новую дату:",
                reply_markup=move_calendar(
                    page,
                    booking_service.tz,
                ),
            )

        # Выбор новой даты
        elif action == "move_day":
            data = await state.get_data()

            if "admin_move_booking_id" not in data:
                raise AdminError(
                    "Начните перенос заново "
                    "через список записей."
                )

            day = date.fromisoformat(parts[2])

            slots = await booking_service.available_slots(
                day
            )

            rows = [
                [
                    (
                        s.starts_at.astimezone(
                            booking_service.tz
                        ).strftime("%H:%M"),
                        "a:move_time:"
                        f"{int(s.starts_at.timestamp())}",
                    )
                ]
                for s in slots
            ]

            rows.append([
                (
                    "Выбрать другую дату",
                    "a:move_cal:0",
                )
            ])

            await q.message.answer(
                (
                    "Выберите свободное время:"
                    if slots
                    else "Свободного времени нет. "
                         "Выберите другую дату."
                ),
                reply_markup=kb(rows),
            )

        # Сохранение переноса
        elif action == "move_time":
            data = await state.get_data()

            if "admin_move_booking_id" not in data:
                raise AdminError(
                    "Начните перенос заново "
                    "через список записей."
                )

            starts = datetime.fromtimestamp(
                int(parts[2]),
                timezone.utc,
            )

            bid = UUID(
                data["admin_move_booking_id"]
            )

            await booking_service.reschedule(
                bid,
                starts,
                admin=True,
            )

            await state.clear()

            local = starts.astimezone(
                booking_service.tz
            )

            await q.message.answer(
                "Запись перенесена на "
                f"{local:%d.%m.%Y в %H:%M}.",
                reply_markup=menu(),
            )

            await notify_client(
                bot,
                booking_service,
                bid,
                "🔄 Администратор Barber Umed "
                "перенёс вашу запись на "
                f"{local:%d.%m.%Y в %H:%M}.",
            )

        # Отказ от переноса
        elif action == "move_stop":
            await state.clear()

            await q.message.answer(
                "Перенос отменён. "
                "Запись не изменена.",
                reply_markup=menu(),
            )

        else:
            await q.message.answer(
                "Неизвестная команда."
            )

    except (
        AdminError,
        BookingError,
        ValueError,
        IndexError,
        OverflowError,
        KeyError,
    ) as exc:
        await q.message.answer(
            "Ошибка: " + escape(str(exc))
        )


@router.message(AdminForm.working_hours)
async def enter_hours(
    m: Message,
    state: FSMContext,
    admin_id: int,
    admin_service: AdminService,
):
    if not allowed(m.from_user, admin_id):
        return

    raw = (m.text or "").strip().lower()

    try:
        if raw == "выходной":
            start = end = None
        else:
            parts = raw.split("-")

            if len(parts) != 2:
                raise ValueError()

            start = time.fromisoformat(
                parts[0].strip()
            )

            end = time.fromisoformat(
                parts[1].strip()
            )

        data = await state.get_data()

        await admin_service.set_hours(
            data["weekday"],
            start,
            end,
        )

    except (ValueError, AdminError):
        await m.answer(
            "Введите 09:00-18:00 "
            "или «выходной»."
        )
        return

    await state.clear()

    await m.answer(
        "График сохранён.",
        reply_markup=menu(),
    )


@router.message(AdminForm.day_off)
async def enter_dayoff(
    m: Message,
    state: FSMContext,
    admin_id: int,
    admin_service: AdminService,
):
    if not allowed(m.from_user, admin_id):
        return

    try:
        day = date.fromisoformat(
            (m.text or "").strip()
        )

        offs = await admin_service.days_off()

        await admin_service.set_day_off(
            day,
            day not in {
                r.day for r in offs
            },
        )

    except ValueError:
        await m.answer(
            "Введите дату в формате ГГГГ-ММ-ДД."
        )
        return

    await state.clear()

    await m.answer(
        "Выходные обновлены. "
        "Уже созданные записи сохранены.",
        reply_markup=menu(),
    )

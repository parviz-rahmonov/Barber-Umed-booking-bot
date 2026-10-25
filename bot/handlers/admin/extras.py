
"""Услуги, профиль мастера, завершение визитов и отзывы."""

from datetime import datetime, timezone
from html import escape
from uuid import UUID
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from sqlalchemy import select

from database.models import (
    Service,
    Booking,
    Review,
    BarberProfile,
    User,
)
from services.admin import AdminService, AdminError
from services.booking import BookingService


router = Router(name="admin_v2")
logger = logging.getLogger(__name__)


class Edit(StatesGroup):
    profile_name = State()
    profile_phone = State()
    profile_address = State()

    new_service_name = State()
    new_service_price = State()

    edit_price = State()
    edit_name = State()


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=callback,
                )
                for text, callback in row
            ]
            for row in rows
        ]
    )


def allowed(q, admin_id):
    return (
        q.from_user is not None
        and q.from_user.id == admin_id
    )


@router.callback_query(F.data == "v:profile")
async def profile(
    q: CallbackQuery,
    booking_service: BookingService,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await q.answer()

    async with booking_service.sessions() as session:
        p = await session.get(BarberProfile, 1)

    if p:
        text = (
            f"💈 Мастер: {escape(p.name)}\n"
            f"📞 Телефон: {escape(p.phone)}\n"
            f"📍 Адрес: {escape(p.address)}"
        )
    else:
        text = "💈 Профиль ещё не заполнен."

    await q.message.answer(
        text,
        reply_markup=kb([
            [
                (
                    "✏️ Изменить профиль",
                    "v:profile_edit",
                )
            ]
        ]),
    )


@router.callback_query(F.data == "v:profile_edit")
async def profile_edit(
    q: CallbackQuery,
    state: FSMContext,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await state.set_state(Edit.profile_name)
    await q.answer()

    await q.message.answer(
        "💈 Введите имя мастера (2–120 символов):"
    )


@router.message(Edit.profile_name)
async def profile_name(
    m: Message,
    state: FSMContext,
    admin_id: int,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    value = (m.text or "").strip()

    if not 2 <= len(value) <= 120:
        return await m.answer(
            "Введите имя от 2 до 120 символов."
        )

    await state.update_data(name=value)
    await state.set_state(Edit.profile_phone)

    await m.answer(
        "📞 Введите рабочий телефон (до 32 символов):"
    )


@router.message(Edit.profile_phone)
async def profile_phone(
    m: Message,
    state: FSMContext,
    admin_id: int,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    value = (m.text or "").strip()

    if not 5 <= len(value) <= 32:
        return await m.answer(
            "Введите корректный рабочий номер."
        )

    await state.update_data(phone=value)
    await state.set_state(Edit.profile_address)

    await m.answer(
        "📍 Введите адрес (до 300 символов):"
    )


@router.message(Edit.profile_address)
async def profile_address(
    m: Message,
    state: FSMContext,
    booking_service: BookingService,
    admin_id: int,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    addr = (m.text or "").strip()

    if not 5 <= len(addr) <= 300:
        return await m.answer(
            "Введите адрес от 5 до 300 символов."
        )

    data = await state.get_data()

    async with booking_service.sessions() as session, session.begin():
        p = await session.get(
            BarberProfile,
            1,
            with_for_update=True,
        )

        if not p:
            session.add(
                BarberProfile(
                    id=1,
                    name=data["name"],
                    phone=data["phone"],
                    address=addr,
                )
            )
        else:
            p.name = data["name"]
            p.phone = data["phone"]
            p.address = addr

    await state.clear()

    await m.answer(
        "✅ Профиль мастера сохранён."
    )


@router.callback_query(F.data == "v:services")
async def services(
    q: CallbackQuery,
    admin_service: AdminService,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await q.answer()

    rows = [
        s
        for s in await admin_service.services()
        if s.name != "Запись к мастеру" and s.is_active
    ]

    buttons = [
        [
            (
                f"✅ {s.name} — {s.price} сомони",
                f"v:service:{s.id}",
            )
        ]
        for s in rows
    ]

    buttons += [
    [
        ("➕ Добавить услугу", "v:service_add")
    ],
    [
        ("🗂 Архив услуг", "v:service_archive")
    ],
    [
        ("◀️ Назад", "a:menu")
    ],
    ]

    await q.message.answer(
        (
            "✂️ Активные услуги и цены:"
            if rows
            else "✂️ Активных услуг пока нет."
        ),
        reply_markup=kb(buttons),
    )


@router.callback_query(F.data == "v:service_archive")
async def service_archive(
    q: CallbackQuery,
    admin_service: AdminService,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await q.answer()

    rows = [
        s
        for s in await admin_service.services()
        if s.name != "Запись к мастеру" and not s.is_active
    ]

    buttons = [
        [
            (
                f"🗂 {s.name} — {s.price} сомони",
                f"v:service:{s.id}",
            )
        ]
        for s in rows
    ]

    buttons.append([
        ("◀️ К услугам", "v:services")
    ])

    await q.message.answer(
        (
            "🗂 Архив услуг:"
            if rows
            else "🗂 Архив пуст."
        ),
        reply_markup=kb(buttons),
    )


@router.callback_query(F.data == "v:service_add")
async def service_add(
    q: CallbackQuery,
    state: FSMContext,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await state.set_state(Edit.new_service_name)
    await q.answer()

    await q.message.answer(
        "✂️ Введите название услуги (2–120 символов):"
    )


@router.message(Edit.new_service_name)
async def new_name(
    m: Message,
    state: FSMContext,
    admin_id: int,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    name = (m.text or "").strip()

    if (
        not 2 <= len(name) <= 120
        or name == "Запись к мастеру"
    ):
        return await m.answer(
            "Неверное название услуги."
        )

    await state.update_data(service_name=name)
    await state.set_state(Edit.new_service_price)

    await m.answer(
        "💰 Введите стоимость в сомони (например 50):"
    )


@router.message(Edit.new_service_price)
async def new_price(
    m: Message,
    state: FSMContext,
    admin_id: int,
    admin_service: AdminService,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    data = await state.get_data()

    try:
        await admin_service.add_service(
            data["service_name"],
            m.text or "",
        )
    except AdminError as exc:
        return await m.answer(
            "❌ " + escape(str(exc))
        )

    await state.clear()

    await m.answer(
        "✅ Услуга добавлена.",
        reply_markup=kb([
            [("✂️ К услугам", "v:services")]
        ]),
    )


@router.callback_query(F.data.startswith("v:service:"))
async def service_detail(
    q: CallbackQuery,
    admin_id: int,
    admin_service: AdminService,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await q.answer()

    sid = int(q.data.split(":")[2])

    svc = next(
        (
            s
            for s in await admin_service.services()
            if (
                s.id == sid
                and s.name != "Запись к мастеру"
            )
        ),
        None,
    )

    if not svc:
        return await q.message.answer(
            "Услуга не найдена."
        )

    actions = [
        [
            (
                "✏️ Изменить название",
                f"v:rename:{sid}",
            )
        ],
        [
            (
                "💰 Изменить цену",
                f"v:price:{sid}",
            )
        ],
    ]

    if svc.is_active:
        actions.append([
            (
                "🗑 Удалить из прайс-листа",
                f"v:delete:{sid}",
            )
        ])
    else:
        actions.append([
            (
                "♻️ Восстановить услугу",
                f"v:toggle:{sid}",
            )
        ])

    actions.append([
        ("◀️ К услугам", "v:services")
    ])

    await q.message.answer(
        f"✂️ {escape(svc.name)}\n"
        f"💰 {svc.price} сомони\n"
        "Статус: "
        f'{"Активна" if svc.is_active else "В архиве"}',
        reply_markup=kb(actions),
    )


@router.callback_query(F.data.startswith("v:rename:"))
async def rename_service(
    q: CallbackQuery,
    state: FSMContext,
    admin_id: int,
    admin_service: AdminService,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    sid = int(q.data.split(":")[2])

    svc = next(
        (
            s
            for s in await admin_service.services()
            if (
                s.id == sid
                and s.name != "Запись к мастеру"
            )
        ),
        None,
    )

    if not svc:
        return await q.answer(
            "Услуга не найдена.",
            show_alert=True,
        )

    await state.set_state(Edit.edit_name)
    await state.update_data(service_id=sid)
    await q.answer()

    await q.message.answer(
        f"✏️ Текущее название: {escape(svc.name)}\n"
        "Введите новое название:"
    )


@router.message(Edit.edit_name)
async def save_name(
    m: Message,
    state: FSMContext,
    admin_id: int,
    admin_service: AdminService,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    data = await state.get_data()

    try:
        await admin_service.update_service(
            data["service_id"],
            name=m.text or "",
        )
    except AdminError as exc:
        return await m.answer(
            "❌ " + escape(str(exc))
        )

    await state.clear()

    await m.answer(
        "✅ Название услуги изменено.",
        reply_markup=kb([
            [("✂️ К услугам", "v:services")]
        ]),
    )


@router.callback_query(F.data.startswith("v:delete:"))
async def ask_delete_service(
    q: CallbackQuery,
    admin_id: int,
    admin_service: AdminService,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    sid = int(q.data.split(":")[2])

    svc = next(
        (
            s
            for s in await admin_service.services()
            if (
                s.id == sid
                and s.name != "Запись к мастеру"
            )
        ),
        None,
    )

    if not svc or not svc.is_active:
        return await q.answer(
            "Услуга уже удалена или не найдена.",
            show_alert=True,
        )

    await q.answer()

    await q.message.answer(
        f"🗑 Удалить «{escape(svc.name)}» "
        "из прайс-листа?\n"
        "Существующие записи сохранятся. "
        "Услугу можно будет восстановить из архива.",
        reply_markup=kb([
            [
                (
                    "✅ Да, удалить",
                    f"v:delete_yes:{sid}",
                )
            ],
            [
                (
                    "◀️ Нет, вернуться",
                    f"v:service:{sid}",
                )
            ],
        ]),
    )


@router.callback_query(F.data.startswith("v:delete_yes:"))
async def delete_service(
    q: CallbackQuery,
    admin_id: int,
    admin_service: AdminService,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    sid = int(q.data.split(":")[2])

    try:
        await admin_service.update_service(
            sid,
            active=False,
        )
    except AdminError as exc:
        return await q.answer(
            str(exc),
            show_alert=True,
        )

    await q.answer(
        "✅ Услуга убрана из прайс-листа."
    )

    await q.message.answer(
        "🗂 Услуга перемещена в архив. "
        "История записей сохранена.",
        reply_markup=kb([
            [("✂️ К услугам", "v:services")]
        ]),
    )


@router.callback_query(F.data.startswith("v:toggle:"))
async def toggle(
    q: CallbackQuery,
    admin_service: AdminService,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    sid = int(q.data.split(":")[2])

    rows = await admin_service.services()

    svc = next(
        (
            s
            for s in rows
            if (
                s.id == sid
                and s.name != "Запись к мастеру"
            )
        ),
        None,
    )

    if not svc:
        return await q.answer(
            "Услуга не найдена.",
            show_alert=True,
        )

    await admin_service.update_service(
        sid,
        active=not svc.is_active,
    )

    await q.answer("✅ Обновлено.")

    await q.message.answer(
        "Статус услуги обновлён.",
        reply_markup=kb([
            [("◀️ К услугам", "v:services")]
        ]),
    )


@router.callback_query(F.data.startswith("v:price:"))
async def price(
    q: CallbackQuery,
    state: FSMContext,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await state.set_state(Edit.edit_price)

    await state.update_data(
        service_id=int(q.data.split(":")[2])
    )

    await q.answer()

    await q.message.answer(
        "💰 Введите новую цену:"
    )


@router.message(Edit.edit_price)
async def save_price(
    m: Message,
    state: FSMContext,
    admin_id: int,
    admin_service: AdminService,
):
    if not m.from_user or m.from_user.id != admin_id:
        return

    data = await state.get_data()

    try:
        await admin_service.update_service(
            data["service_id"],
            price=m.text or "",
        )
    except AdminError as exc:
        return await m.answer(
            "❌ " + escape(str(exc))
        )

    await state.clear()

    await m.answer(
        "✅ Цена изменена.",
        reply_markup=kb([
            [("✂️ К услугам", "v:services")]
        ]),
    )


@router.callback_query(F.data.startswith("v:complete:"))
async def complete(
    q: CallbackQuery,
    admin_id: int,
    admin_service: AdminService,
    booking_service: BookingService,
    bot: Bot,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    bid = UUID(q.data.split(":")[2])

    try:
        await admin_service.set_status(
            bid,
            "completed",
        )
    except AdminError as exc:
        return await q.answer(
            str(exc),
            show_alert=True,
        )

    await q.answer(
        "✅ Посещение завершено."
    )

    await q.message.answer(
        "✅ Посещение отмечено завершённым. "
        "Клиент может оставить отзыв."
    )

    async with booking_service.sessions() as session:
        b = await session.get(Booking, bid)

        user = (
            await session.get(User, b.user_id)
            if b
            else None
        )

    if user:
        try:
            await bot.send_message(
                user.telegram_id,
                "✅ Ваше посещение Barber Umed завершено.\n"
                "⭐ Теперь можете оставить отзыв "
                "в разделе «Отзывы».",
            )
        except Exception:
            logger.exception(
                "Уведомление о завершении не доставлено"
            )


@router.callback_query(F.data == "v:reviews")
async def review_list(
    q: CallbackQuery,
    booking_service: BookingService,
    admin_id: int,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    await q.answer()

    async with booking_service.sessions() as session:
        reviews = (
            await session.scalars(
                select(Review)
                .where(Review.approved.is_(False))
                .order_by(Review.created_at)
                .limit(30)
            )
        ).all()

    if not reviews:
        return await q.message.answer(
            "⭐ Отзывов на проверку нет."
        )

    for r in reviews:
        await q.message.answer(
            f"⭐ Оценка: {r.rating}/5\n"
            f"✍️ {escape(r.comment)}",
            reply_markup=kb([
                [
                    (
                        "✅ Одобрить",
                        f"v:review_ok:{r.id}",
                    )
                ],
                [
                    (
                        "❌ Отклонить",
                        f"v:review_no:{r.id}",
                    )
                ],
            ]),
        )


@router.callback_query(
    F.data.startswith(
        ("v:review_ok:", "v:review_no:")
    )
)
async def review_moderate(
    q: CallbackQuery,
    admin_id: int,
    booking_service: BookingService,
):
    if not allowed(q, admin_id):
        return await q.answer(
            "Нет доступа.",
            show_alert=True,
        )

    parts = q.data.split(":")
    approve = parts[1] == "review_ok"
    rid = int(parts[2])

    async with booking_service.sessions() as session, session.begin():
        r = await session.get(
            Review,
            rid,
            with_for_update=True,
        )

        if not r or r.approved:
            return await q.answer(
                "Отзыв уже обработан.",
                show_alert=True,
            )

        if approve:
            r.approved = True
        else:
            await session.delete(r)

    await q.answer(
        "✅ Одобрено."
        if approve
        else "❌ Отклонено."
    )

    await q.message.answer(
        "Отзыв обработан."
    )

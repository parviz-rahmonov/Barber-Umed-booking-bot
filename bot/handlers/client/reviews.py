"""Отзывы: только по завершённым записям и только одна оценка на запись."""
from html import escape
from uuid import UUID
from datetime import datetime, timezone
from aiogram import F, Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from database.models import Booking, Review, User
from services.booking import BookingService
from bot.localization import BTN_REVIEWS

router = Router(name='client_reviews')

class ReviewForm(StatesGroup):
    comment = State()


def keys(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c) for t,c in row] for row in rows])

@router.message(F.text == BTN_REVIEWS)
async def reviews_menu(m: Message, booking_service: BookingService):
    async with booking_service.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == m.from_user.id))
        reviews = (await session.scalars(select(Review).where(Review.approved.is_(True)).order_by(Review.created_at.desc()).limit(10))).all()
        pending = []
        if user:
            used = select(Review.booking_id).where(Review.user_id == user.id)
            pending = (await session.scalars(select(Booking).where(
                Booking.user_id == user.id, Booking.status == 'completed',
                ~Booking.id.in_(used)
            ).order_by(Booking.starts_at.desc()).limit(10))).all()
    await m.answer('⭐ Отзывы клиентов:\n' + ('\n'.join(f"{'⭐' * r.rating} {escape(r.comment)}" for r in reviews) if reviews else 'Пока нет опубликованных отзывов.'))
    for b in pending:
        await m.answer(f'⭐ Оцените посещение {b.starts_at.astimezone(booking_service.tz):%d.%m.%Y}:', reply_markup=keys([[('⭐'*n, f'r:rate:{b.id}:{n}')] for n in range(1,6)]))

@router.callback_query(F.data.startswith('r:rate:'))
async def rate(q: CallbackQuery, state: FSMContext, booking_service: BookingService):
    try:
        _, _, raw_id, raw_rating = q.data.split(':')
        bid, rating = UUID(raw_id), int(raw_rating)
        if rating not in range(1,6): raise ValueError()
    except (ValueError, TypeError):
        await q.answer('Неверная оценка.', show_alert=True); return
    async with booking_service.sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == q.from_user.id))
        b = await session.get(Booking, bid)
        existing = await session.scalar(select(Review.id).where(Review.booking_id == bid))
    if not user or not b or b.user_id != user.id or b.status != 'completed' or existing:
        await q.answer('Для этой записи отзыв недоступен.', show_alert=True); return
    await state.set_state(ReviewForm.comment)
    await state.update_data(review_bid=str(bid), review_rating=rating)
    await q.answer()
    if q.message: await q.message.answer('✍️ Напишите отзыв до 500 символов:')

@router.message(ReviewForm.comment)
async def comment(m: Message, state: FSMContext, booking_service: BookingService, bot: Bot, admin_id: int):
    content = (m.text or '').strip()
    if not 2 <= len(content) <= 500:
        await m.answer('Введите отзыв от 2 до 500 символов.'); return
    data = await state.get_data()
    bid = UUID(data['review_bid'])
    try:
        async with booking_service.sessions() as session, session.begin():
            user = await session.scalar(select(User).where(User.telegram_id == m.from_user.id))
            b = await session.get(Booking, bid, with_for_update=True)
            if not user or not b or b.user_id != user.id or b.status != 'completed':
                await m.answer('Отзыв для этого посещения недоступен.'); await state.clear(); return
            existing = await session.scalar(select(Review.id).where(Review.booking_id == bid))
            if existing:
                await m.answer('Для этой записи отзыв уже существует.'); await state.clear(); return
            session.add(Review(booking_id=bid,user_id=user.id,rating=data['review_rating'],comment=content,approved=False))
    except IntegrityError:
        await m.answer('Отзыв для этого посещения уже отправлен.'); await state.clear(); return
    await state.clear()
    await m.answer('✅ Спасибо! Отзыв отправлен на проверку администратору.')
    try:
        await bot.send_message(admin_id, f'⭐ Новый отзыв на проверку\nОценка: {data["review_rating"]}/5\nТекст: {escape(content)}')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Уведомление об отзыве не доставлено')

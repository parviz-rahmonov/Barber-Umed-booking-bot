"""Barber Umed V1.1: имя, телефон, дата, время. Без выбора услуги."""
from __future__ import annotations
import logging
import re
from datetime import date, datetime, timedelta, timezone
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo
from aiogram import F, Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from database.models import Booking, User, Service, BarberProfile
from services.booking import BookingService, BookingError
from bot.localization import russian_date_short, BTN_BOOK, BTN_MINE

router = Router(name='client_booking')
PHONE = re.compile(r'^\+?[0-9][0-9 ()-]{6,19}$')
INTERNAL_SERVICE = 'Запись к мастеру'

class Form(StatesGroup):
    name = State()
    phone = State()
    confirm = State()

def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t,callback_data=c) for t,c in row] for row in rows])

def calendar(page: int, tz: ZoneInfo, prefix='b'):
    today = datetime.now(tz).date()
    days = [today+timedelta(days=i) for i in range(page*7, min(page*7+7,31))]
    rows = [[(russian_date_short(day), f'{prefix}:day:{day.isoformat()}')] for day in days]
    nav=[]
    if page: nav.append(('◀ Назад',f'{prefix}:cal:{page-1}'))
    if page < 4: nav.append(('Вперёд ▶',f'{prefix}:cal:{page+1}'))
    if nav: rows.append(nav)
    rows.append([('Отмена','b:stop')])
    return keyboard(rows)

@router.message(F.text == BTN_BOOK)
async def begin(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.name)
    await m.answer('Как вас зовут? Введите имя:')

@router.callback_query(F.data == 'b:stop')
async def stop(q: CallbackQuery, state: FSMContext):
    await state.clear(); await q.answer()
    if q.message: await q.message.answer('Действие отменено.')

@router.message(Form.name)
async def name_input(m: Message, state: FSMContext):
    name=(m.text or '').strip()
    if not 2 <= len(name) <= 120:
        await m.answer('Введите имя от 2 до 120 символов.'); return
    await state.update_data(name=name)
    await state.set_state(Form.phone)
    await m.answer('Введите номер телефона, например +992900000000:')

@router.message(Form.phone)
async def phone_input(m: Message, state: FSMContext, booking_service: BookingService):
    phone=(m.text or '').strip()
    if len(phone)>32 or not PHONE.fullmatch(phone):
        await m.answer('Некорректный номер. Введите телефон с кодом страны.'); return
    await state.update_data(phone=phone)
    await state.set_state(None)
    async with booking_service.sessions() as session:
        services = (await session.scalars(select(Service).where(
            Service.is_active.is_(True), Service.name != INTERNAL_SERVICE
        ).order_by(Service.name))).all()
    if not services:
        await m.answer("✂️ Пока нет доступных услуг. Обратитесь к мастеру.")
        return
    await m.answer("✂️ Выберите услугу:", reply_markup=keyboard([
        [(f"✂️ {svc.name} — {svc.price} сомони", f"b:service:{svc.id}")]
        for svc in services
    ]))

@router.callback_query(F.data.startswith('b:service:'))
async def choose_service(q: CallbackQuery, state: FSMContext, booking_service: BookingService):
    data = await state.get_data()
    if not all(k in data for k in ('name', 'phone')):
        await q.answer('Начните запись заново.', show_alert=True)
        return
    try:
        service_id = int(q.data.split(':')[2])
    except (IndexError, ValueError):
        await q.answer('Неверная услуга.', show_alert=True)
        return
    async with booking_service.sessions() as session:
        svc = await session.get(Service, service_id)
    if not svc or not svc.is_active or svc.name == INTERNAL_SERVICE:
        await q.answer('Услуга недоступна.', show_alert=True)
        return
    await state.update_data(service_id=svc.id)
    await q.answer()
    if q.message:
        await q.message.answer('📅 Выберите дату записи:', reply_markup=calendar(0, booking_service.tz))

@router.callback_query(F.data.startswith(('b:cal:','m:cal:')))
async def change_page(q: CallbackQuery, state: FSMContext, booking_service: BookingService):
    prefix=q.data[0]; data=await state.get_data()
    if (prefix=='b' and not all(k in data for k in ('name','phone','service_id'))) or (prefix=='m' and 'move_booking_id' not in data):
        await q.answer('Начните действие заново.',show_alert=True); return
    try: page=int(q.data.split(':')[2])
    except (ValueError,IndexError): page=-1
    if not 0<=page<=4:
        await q.answer('Неверная страница.',show_alert=True); return
    await q.answer()
    if q.message: await q.message.edit_reply_markup(reply_markup=calendar(page,booking_service.tz,prefix))

@router.callback_query(F.data.startswith(('b:day:','m:day:')))
async def choose_day(q: CallbackQuery, state: FSMContext, booking_service: BookingService):
    prefix=q.data[0]; data=await state.get_data()
    if (prefix=='b' and not all(k in data for k in ('name','phone','service_id'))) or (prefix=='m' and 'move_booking_id' not in data):
        await q.answer('Начните действие заново.',show_alert=True); return
    try: day=date.fromisoformat(q.data.split(':')[2])
    except (ValueError,IndexError):
        await q.answer('Неверная дата.',show_alert=True); return
    slots=await booking_service.available_slots(day)
    await q.answer()
    if q.message:
        rows=[[(s.starts_at.astimezone(booking_service.tz).strftime('%H:%M'),f'{prefix}:time:{int(s.starts_at.timestamp())}')] for s in slots]
        rows.append([('Выбрать другой день',f'{prefix}:cal:0')])
        await q.message.answer('Выберите свободное время:' if slots else 'Свободного времени нет. Выберите другой день.',reply_markup=keyboard(rows))

@router.callback_query(F.data == 'b:confirm')
async def confirm(q: CallbackQuery, state: FSMContext, booking_service: BookingService, bot: Bot, admin_id: int):
    if await state.get_state()!=Form.confirm.state:
        await q.answer('Запись уже обработана.',show_alert=True); return
    await state.set_state(None)
    data=await state.get_data()
    await q.answer()
    try:
        async with booking_service.sessions() as session:
            async with session.begin():
                service=await session.get(Service, int(data['service_id']))
                if not service or not service.is_active or service.name == INTERNAL_SERVICE:
                    raise BookingError('Услуга больше недоступна.')
                service_id=service.id
                stmt=insert(User).values(telegram_id=q.from_user.id,name=data['name'],phone=data['phone'])
                stmt=stmt.on_conflict_do_update(index_elements=[User.telegram_id],set_={'name':data['name'],'phone':data['phone']}).returning(User.id)
                user_id=(await session.execute(stmt)).scalar_one()
        bid=await booking_service.create(user_id=user_id,service_id=service_id,starts_at=datetime.fromisoformat(data['starts_at']))
    except BookingError as exc:
        await state.clear()
        if q.message: await q.message.answer('Запись не создана: '+escape(str(exc))+' Выберите время заново.')
        return
    await state.clear()
    when=datetime.fromisoformat(data['starts_at']).astimezone(booking_service.tz)
    async with booking_service.sessions() as session:
        profile = await session.get(BarberProfile, 1)
    master_info = (f"\n💈 Мастер: {escape(profile.name)}\n📍 {escape(profile.address)}" if profile else "")
    if q.message:
        await q.message.answer(f'✅ Вы записаны!\n✂️ Услуга: {escape(service.name)}\n💰 Цена: {service.price} сомони\n📅 {when:%d.%m.%Y}\n🕒 {when:%H:%M}' + master_info)
    try:
        await bot.send_message(admin_id, f'✅ Новая запись\n👤 Клиент: {escape(data["name"])}\n📞 Телефон: {escape(data["phone"])}\n✂️ Услуга: {escape(service.name)}\n💰 Стоимость: {service.price} сомони\n📅 Дата: {when:%d.%m.%Y}\n🕒 Время: {when:%H:%M}')
    except Exception:
        logging.getLogger(__name__).exception('Уведомление владельцу не отправлено: %s',bid)

@router.callback_query(F.data.startswith('b:time:'))
async def choose_time(q: CallbackQuery, state: FSMContext, booking_service: BookingService):
    data = await state.get_data()
    if not all(k in data for k in ("name", "phone", "service_id")):
        await q.answer('Начните запись заново.',show_alert=True); return
    try: starts=datetime.fromtimestamp(int(q.data.split(':')[2]),timezone.utc)
    except (ValueError,IndexError,OverflowError):
        await q.answer('Неверное время.',show_alert=True); return
    slots=await booking_service.available_slots(starts.astimezone(booking_service.tz).date())
    if starts not in {s.starts_at for s in slots}:
        await q.answer('Время занято. Выберите другое.',show_alert=True); return
    await state.update_data(starts_at=starts.isoformat())
    await state.set_state(Form.confirm)
    data=await state.get_data()
    await q.answer()
    if q.message:
        local=starts.astimezone(booking_service.tz)
        await q.message.answer(f'✅ Проверьте запись:\n👤 Клиент: {escape(data["name"])}\n📞 Телефон: {escape(data["phone"])}\n📅 Дата: {local:%d.%m.%Y}\n🕒 Время: {local:%H:%M}',reply_markup=keyboard([[('Подтвердить','b:confirm')],[('Отмена','b:stop')]]))

@router.message(F.text == BTN_MINE)
async def my_bookings(m: Message, booking_service: BookingService):
    async with booking_service.sessions() as session:
        user=await session.scalar(select(User).where(User.telegram_id==m.from_user.id))
        if not user:
            await m.answer('У вас пока нет записей.'); return
        rows=(await session.scalars(select(Booking).where(Booking.user_id==user.id,Booking.status=='confirmed',Booking.starts_at>=datetime.now(timezone.utc)).order_by(Booking.starts_at).limit(20))).all()
    if not rows:
        await m.answer('У вас нет предстоящих записей.'); return
    for b in rows:
        local=b.starts_at.astimezone(booking_service.tz)
        await m.answer(f'Запись: {local:%d.%m.%Y %H:%M}',reply_markup=keyboard([[('Отменить',f'b:cancel:{b.id}'),('Перенести',f'b:move:{b.id}')]]))


@router.callback_query(F.data.startswith("b:cancel:"))
async def cancel(
    q: CallbackQuery,
    booking_service: BookingService,
    bot: Bot,
    admin_id: int,
):
    try:
        bid = UUID(q.data.split(":")[2])
    except (ValueError, IndexError):
        await q.answer("Неверная запись.", show_alert=True)
        return

    # Сначала получаем данные записи и клиента.
    async with booking_service.sessions() as session:
        user = await session.scalar(
            select(User).where(
                User.telegram_id == q.from_user.id
            )
        )

        booking = await session.get(Booking, bid)

        if (
            user is None
            or booking is None
            or booking.user_id != user.id
        ):
            await q.answer(
                "Запись не найдена.",
                show_alert=True,
            )
            return

        client_name = user.name
        client_phone = user.phone
        service = await session.get(Service, booking.service_id)
        service_name = service.name if service else 'не указана' 

        local_time = booking.starts_at.astimezone(
            booking_service.tz
        )

    # Отменяем запись через существующий сервис.
    try:
        await booking_service.cancel(
            bid,
            user_id=user.id,
        )
    except BookingError as exc:
        await q.answer(str(exc), show_alert=True)
        return

    await q.answer("Запись отменена.")

    if q.message:
        await q.message.answer(
            "✅ Ваша запись успешно отменена."
        )

    # Уведомляем администратора.
    notification = (
        "❌ Клиент отменил запись\n\n"
        f"👤 Клиент: {escape(client_name)}\n"
        f"📞 Телефон: {escape(client_phone or 'не указан')}\n"
        f"✂️ Услуга: {escape(service_name)}\n"
        f"📅 Дата: {local_time:%d.%m.%Y}\n"
        f"🕒 Время: {local_time:%H:%M}\n\n"
        "✅ Время снова доступно для записи."
    )

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=notification,
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "Не удалось уведомить администратора "
            "об отмене записи %s",
            bid,
        )


@router.callback_query(F.data.startswith('b:move:'))
async def move_start(q: CallbackQuery, state: FSMContext, booking_service: BookingService):
    try: bid=UUID(q.data.split(':')[2])
    except (ValueError,IndexError):
        await q.answer('Неверная запись.',show_alert=True); return
    async with booking_service.sessions() as session:
        user=await session.scalar(select(User).where(User.telegram_id==q.from_user.id))
        row=await session.get(Booking,bid)
    if not user or not row or row.user_id!=user.id or row.status!='confirmed' or row.starts_at < datetime.now(timezone.utc)+timedelta(hours=2):
        await q.answer('Перенос недоступен.',show_alert=True); return
    await state.clear()
    await state.update_data(move_booking_id=str(bid))
    await q.answer()
    if q.message: await q.message.answer('Выберите новую дату:',reply_markup=calendar(0,booking_service.tz,'m'))

@router.callback_query(F.data.startswith('m:time:'))
async def move_commit(q: CallbackQuery, state: FSMContext, booking_service: BookingService, bot: Bot, admin_id: int):
    data=await state.get_data()
    if 'move_booking_id' not in data:
        await q.answer('Начните перенос заново.',show_alert=True); return
    try: starts=datetime.fromtimestamp(int(q.data.split(':')[2]),timezone.utc)
    except (ValueError,IndexError,OverflowError):
        await q.answer('Неверное время.',show_alert=True); return
    async with booking_service.sessions() as session:
        user=await session.scalar(select(User).where(User.telegram_id==q.from_user.id))
        old=await session.get(Booking, UUID(data['move_booking_id']))
        old_start=old.starts_at if old else None
        svc=await session.get(Service, old.service_id) if old else None
    await q.answer()
    try:
        if not user or not old or old.user_id != user.id:
            raise BookingError('Запись не найдена.')
        await booking_service.reschedule(UUID(data['move_booking_id']),starts,user_id=user.id)
    except BookingError as exc:
        if q.message: await q.message.answer('Перенос не выполнен: '+escape(str(exc)))
        return
    await state.clear()
    old_local = old_start.astimezone(booking_service.tz)
    new_local = starts.astimezone(booking_service.tz)
    if q.message: await q.message.answer('🔄 Запись перенесена на ' + new_local.strftime('%d.%m.%Y %H:%M'))
    try:
        await bot.send_message(admin_id,
            f'🔄 Клиент перенёс запись\n👤 Клиент: {escape(user.name)}\n📞 Телефон: {escape(user.phone)}\n'
            f'✂️ Услуга: {escape(svc.name) if svc else "не указана"}\n'
            f'📅 Было: {old_local:%d.%m.%Y, %H:%M}\n📅 Стало: {new_local:%d.%m.%Y, %H:%M}')
    except Exception:
        logging.getLogger(__name__).exception('Не удалось уведомить администратора о переносе %s', old.id)

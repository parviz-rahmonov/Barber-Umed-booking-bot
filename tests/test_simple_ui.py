from bot.handlers.client.start import MENU
from bot.handlers.client.booking import INTERNAL_SERVICE, calendar
from bot.handlers.admin.start import menu
from bot.localization import BTN_BOOK, BTN_MINE, BTN_PRICES, BTN_BARBER, BTN_REVIEWS
from zoneinfo import ZoneInfo


def test_client_v2_menu():
    names = [b.text for row in MENU.keyboard for b in row]
    assert names == [BTN_BOOK, BTN_MINE, BTN_PRICES, BTN_BARBER, BTN_REVIEWS]


def test_internal_service_not_shown_on_calendar():
    assert INTERNAL_SERVICE == 'Запись к мастеру'
    assert 'service:' not in str(calendar(0, ZoneInfo('Asia/Dushanbe')).model_dump())


def test_admin_v2_menu():
    labels = [b.text for row in menu().inline_keyboard for b in row]
    assert '🗓 Расписание' in labels
    assert '📋 Записи' in labels
    assert '✂️ Услуги и цены' in labels
    assert '💈 О мастере' in labels
    assert '⭐ Отзывы' in labels

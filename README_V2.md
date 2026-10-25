# Barber Umed V2.0 — исходный проект для проверки

## Запуск на Windows (Python 3.12, Docker Desktop)

# Barber Umed | Telegram Booking Bot

A Telegram appointment booking system for a single-barber business, built with Python, aiogram 3, PostgreSQL and SQLAlchemy.

## Features

**For customers**
- Book a barber appointment through Telegram
- Choose a service and view its price
- Browse available dates and time slots
- Cancel or reschedule appointments
- View barber contact information
- Leave reviews after completed visits

**For administrators**
- Manage services and prices
- Rename, archive and restore services
- Configure working hours and days off
- View and manage appointments
- Manage barber profile information
- Moderate customer reviews

**Booking rules**
- Single barber
- 60-minute appointments
- Booking window of up to 30 days
- PostgreSQL protection against overlapping appointments
- Customer cancellations and rescheduling subject to advance-notice rules

## Technology Stack

- Python 3.12
- aiogram 3
- PostgreSQL 16
- SQLAlchemy (async)
- asyncpg
- Alembic
- Docker Compose
- pytest

## Getting Started

1. Clone the repository.
2. Create a Python virtual environment.
3. Install dependencies using `pip install -r requirements-dev.txt`.
4. Copy `.env.example` to `.env` and configure environment variables.
5. Start PostgreSQL using `docker compose up -d db`.
6. Apply database migrations using `python -m alembic upgrade head`.
7. Start the bot using `python main.py`.

Only PostgreSQL runs in Docker in this local setup. The Telegram bot runs directly in Python.

## Testing

Run:

`python -m pytest -q`

Automated tests cover selected application behavior. End-to-end Telegram testing and reminder delivery require separate verification.

## Appointment Reminders

The project includes support for scheduling appointment reminders 24 hours and 2 hours before visits. End-to-end delivery verification is required before production deployment.

## Security

Credentials must be stored in `.env`, which is excluded from version control. Never commit actual bot tokens, database passwords or customer information.

## Project Status

Version 2.0.0 — release candidate undergoing final integration verification.

## Developer

**Rahmonov Parviz**

Python / Telegram Bot Developer

GitHub: [parviz-rahmonov](https://github.com/parviz-rahmonov)

1. Скопируйте `.env.example` в `.env` и задайте собственные BOT_TOKEN, ADMIN_ID и POSTGRES_PASSWORD. В DATABASE_URL используйте тот же пароль (при спецсимволах сделайте URL-encoding).
2. В терминале из папки проекта: `python -m venv .venv`, затем `.venv\Scripts\Activate.ps1`.
3. `pip install -r requirements-dev.txt`
4. `docker compose up -d db` — запускает **только PostgreSQL** на 127.0.0.1:5433.
5. `python -m alembic upgrade head` — должна примениться миграция `0003_v2_profile_reviews`.
6. `python -m database.check`
7. `python -m pytest -q`
8. `python main.py` (не запускайте одновременно другую копию бота).

Первое действие: `/admin` → «💈 О мастере» заполнить профиль, затем «✂️ Услуги и цены» добавить услуги и указать цены, затем настроить расписание.

## Данные и безопасность

Тестовые данные V1.1 намеренно не включены в архив. Не публикуйте `.env`, не отправляйте пароль или токен. **Не применяйте глобальные команды docker prune**: они могут затронуть Course Center Bot. Используйте отдельное имя Compose-проекта `barber_umed_v2` и том `barber_umed_v2_barber_v2_pgdata` (точное имя проверьте `docker volume ls`).

## Ограничения проверки

Модульные тесты не заменяют проверку с PostgreSQL и двумя Telegram-аккаунтами. Перед сдачей проверьте оплату не требуется, запись, смену цены после бронирования, перенос, отмену, завершение визита, модерацию отзывов и недоступность кнопок постороннему пользователю.

## Проверка перед коммерческой сдачей

Это **кандидат V2.0 для интеграционного тестирования**, а не подтверждённый производственный релиз. На стороне разработчика не было доступа к сетевым сервисам и установленному aiogram, поэтому полный pytest и реальные Telegram/PostgreSQL тесты должны быть выполнены на Windows. Обнаруженные ошибки фиксируются и исправляются до демонстрации заказчику.

# Barber Umed V2.0 — System Architecture

> **Status:** V2.0 integration candidate. This document describes the repository implementation and separates implemented mechanisms from production verification.

## 1. Purpose and scope

Barber Umed is a **single-barber Telegram appointment booking system** with a Russian-language customer interface and one administrator.

- Appointments are **60 minutes** long.
- Customers choose one active service and a free time slot, up to **30 days ahead**.
- Customers can cancel or reschedule with a **two-hour notice**; administrators can manage bookings directly.
- Administrators manage working hours, days off, barber information, service names/prices and archived services.
- Reviews are associated with completed bookings and moderated before publication.
- Appointment reminders are scheduled for **24 hours** and **2 hours** before a booking, when those reminder times are still in the future.

Out of scope: multi-barber scheduling, website, online payment processing and marketing campaigns. Legacy `payments` code/table are present in the repository but are not part of the intended V2.0 customer workflow.

## 2. High-level architecture

```mermaid
flowchart TB
    Customer[Telegram customer]
    Admin[Telegram administrator]
    Telegram[Telegram Bot API]
    App[Python 3.12 process: main.py]
    Handlers[aiogram routers / FSM]
    Booking[BookingService]
    Administration[AdminService]
    Reminders[ReminderWorker]
    ORM[SQLAlchemy async + asyncpg]
    DB[(PostgreSQL 16)]
    Migration[Alembic migrations]

    Customer --> Telegram
    Admin --> Telegram
    Telegram <--> App
    App --> Handlers
    App --> Reminders
    Handlers --> Booking
    Handlers --> Administration
    Booking --> ORM
    Administration --> ORM
    Reminders --> ORM
    ORM <--> DB
    Reminders -->|send_message| Telegram
    Migration --> DB
```

**Local runtime:** Docker Compose starts **only PostgreSQL** (`db`, bound to `127.0.0.1:5433`); `python main.py` runs the Telegram polling application and its background reminder task. Do not start a second bot process against the same token.

## 3. Repository structure

```text
.
├── main.py                     # aiogram Dispatcher, DI, polling, reminder task
├── config.py                   # Pydantic environment settings
├── compose.yaml                # PostgreSQL 16 service and named volume
├── Dockerfile                  # Container build definition (not used in local DB-only run)
├── .env.example                # Configuration placeholders; no real credentials
├── bot/
│   ├── handlers/
│   │   ├── admin/
│   │   │   ├── start.py        # Admin menu, schedule and booking actions
│   │   │   └── extras.py       # Profile, service editing and review moderation
│   │   └── client/
│   │       ├── start.py        # Entry and customer menu
│   │       ├── booking.py      # Booking, cancellation and rescheduling flow
│   │       ├── info.py         # Barber information
│   │       └── reviews.py      # Customer reviews
│   └── localization.py         # Russian interface text/date helpers
├── services/
│   ├── booking.py              # Booking invariants and scheduling logic
│   ├── admin.py                # Administrator business operations
│   └── reminders.py            # Background reminder delivery
├── database/
│   ├── base.py                 # ORM declarative Base
│   ├── models/                 # SQLAlchemy models
│   ├── session.py              # Async engine and session factory
│   └── check.py                # Database connectivity/schema diagnostic
├── migrations/
│   ├── env.py                  # Alembic runtime
│   └── versions/
│       ├── 0001_initial.py
│       ├── 0002_internal_service.py
│       └── 0003_v2_profile_reviews.py
└── tests/                      # pytest checks
```

## 4. Layers and responsibilities

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Transport/UI | `bot/handlers/**` | Telegram commands, callback routing, buttons, FSM data, human-readable messages |
| Application/domain | `services/booking.py` | Slot generation, availability, create/cancel/reschedule and booking rules |
| Administration | `services/admin.py` | Manage service catalog, working hours, days off and booking statuses |
| Background work | `services/reminders.py` | Find due reminders, deliver through Bot API, record attempts/status |
| Persistence | `database/models`, `database/session.py` | SQLAlchemy async ORM and transaction/session lifecycle |
| Schema changes | `migrations/versions` | Versioned PostgreSQL DDL |
| Startup/config | `main.py`, `config.py` | Environment validation, dependency injection, polling and shutdown |

Handlers should keep data validation and persistence details in services when possible. Database mutations for a booking and its reminder rows occur in a shared transaction.

## 5. Data model

```mermaid
erDiagram
    USERS ||--o{ BOOKINGS : makes
    SERVICES ||--o{ BOOKINGS : selected_for
    BOOKINGS ||--o{ NOTIFICATIONS : schedules
    BOOKINGS ||--o| REVIEWS : receives
    USERS ||--o{ REVIEWS : writes
    BOOKINGS ||--o{ PAYMENTS : legacy

    USERS {
        bigint id PK
        bigint telegram_id
        string name
        string phone
    }
    SERVICES {
        int id PK
        string name
        decimal price
        bool is_active
    }
    BOOKINGS {
        uuid id PK
        bigint user_id FK
        int service_id FK
        datetime starts_at
        datetime ends_at
        decimal price_snapshot
        string status
    }
    NOTIFICATIONS {
        bigint id PK
        uuid booking_id FK
        string kind
        datetime scheduled_at
        string status
        int attempts
    }
    REVIEWS {
        bigint id PK
        uuid booking_id FK
        bigint user_id FK
        int rating
        bool approved
    }
    PAYMENTS {
        bigint id PK
        uuid booking_id FK
    }
```

Additional configuration tables:

- `working_hours` — weekday intervals.
- `days_off` — date-based exceptions.
- `barber_profile` — name, work phone and address for the single barber.
- `alembic_version` — current migration version.

**Key invariants:**

- PostgreSQL enforces `ends_at = starts_at + interval '1 hour'`.
- A PostgreSQL exclusion constraint from migration `0001_initial` protects against overlapping blocking booking intervals, including concurrent booking requests.
- `price_snapshot` preserves the booked price even if the administrator later edits a service price.
- Service deletion in the administrator UI means `is_active = false`; historical bookings retain their foreign keys.
- `notifications` has a unique `(booking_id, kind)` constraint.

## 6. Booking lifecycle

```mermaid
sequenceDiagram
    participant C as Customer
    participant T as aiogram handlers
    participant S as BookingService
    participant DB as PostgreSQL
    participant W as ReminderWorker

    C->>T: Name, phone, service, date and time
    T->>S: available_slots(date)
    S->>DB: Read schedule, days off and occupied slots
    DB-->>S: Available slots
    S-->>T: Slots
    C->>T: Confirm booking
    T->>S: create(user_id, service_id, starts_at)
    S->>DB: Validate and INSERT booking
    S->>DB: INSERT future reminder jobs
    DB-->>S: Commit (or overlap error)
    S-->>T: Booking ID
    T-->>C: Confirmation
    W->>DB: Poll due pending jobs
    W->>C: Telegram reminder (via Bot API)
    W->>DB: Mark sent / retry
```

1. Available slots use working hours, days off, the 30-day horizon and a minimum one-hour lead time.
2. The service is validated as active again at booking creation.
3. The transaction persists a confirmed booking and its future reminder jobs together.
4. An overlap is rejected by PostgreSQL, not solely by UI slot filtering.
5. On cancellation, the booking becomes `cancelled` and queued reminders are removed.
6. On rescheduling, the same booking ID remains; old reminders are removed and new future reminders are queued.

Booking statuses include `confirmed`, `completed`, `cancelled` and `no_show`.

## 7. Reminder delivery

`services/reminders.py` contains an asynchronous worker started alongside Telegram polling. The persisted queue is in `notifications`.

- Kinds: `reminder_24h` and `reminder_2h`.
- Jobs are created only if their scheduled time is in the future.
- Due pending jobs are selected with PostgreSQL row locking (`FOR UPDATE SKIP LOCKED`).
- A worker checks the booking is still confirmed and has not started before delivery.
- Telegram API errors increment attempt count; current code retries up to three times.
- Job states include `pending`, `sending`, `sent`, `failed` and `cancelled`.

**Delivery semantics:** Telegram delivery and PostgreSQL updates are not one atomic transaction. Exactly-once delivery cannot be guaranteed after crashes or network uncertainty. Operational testing must verify retries, duplicate prevention, cancellation races and shutdown behavior. The polling process must remain running for scheduled delivery.

## 8. Runtime configuration and security

Required `.env` values:

```dotenv
BOT_TOKEN=REPLACE_ME
ADMIN_ID=123456789
POSTGRES_PASSWORD=REPLACE_ME
DATABASE_URL=postgresql+asyncpg://barber:REPLACE_ME@127.0.0.1:5433/barber
TIMEZONE=Asia/Dushanbe
LOG_LEVEL=INFO
```

- Do not commit `.env`; use `.env.example` as a template.
- Administrator Telegram actions are guarded by `ADMIN_ID` checks.
- PostgreSQL is exposed to the Windows host on loopback only.
- Avoid logging tokens or customer phone numbers unnecessarily.
- Use separate Docker Compose projects/volumes for unrelated applications.

## 9. Development and operational commands

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
docker compose up -d db
python -m alembic upgrade head
python -m database.check
python -m pytest -q
python main.py
```

To stop polling, press `Ctrl+C`. Avoid `docker compose down -v` unless deliberate data deletion is intended.

## 10. Verification status and known issues

The local developer reported **16 pytest tests passing** and successful execution of Alembic migration `0003_v2_profile_reviews`. This does **not** establish end-to-end correctness of notification delivery, concurrency, Telegram API errors or recovery after interrupted operations.

**Review before production release:**

1. **Startup issue:** at the time this architecture document was written, `main.py` starts `ReminderWorker` twice; consolidate to one task and ensure it is cancelled/awaited during shutdown.
2. Test reminder scheduling and delivery for 24-hour and 2-hour cases, including rescheduling and cancellation.
3. Test booking concurrency against a real PostgreSQL instance.
4. Check whether an in-flight reminder can be delivered after simultaneous cancellation and define the desired behavior.
5. Add automated integration tests and verify a clean GitHub Actions run.
6. Verify the README and `.env.example` are current before assigning a production release tag.

**Version:** V2.0 architecture, documented against the current repository implementation.

"""Stage 2: initial schema and non-overlapping booking intervals.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False, unique=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('phone', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('services',
        sa.Column('id', sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False, unique=True),
        sa.Column('price', sa.Numeric(12,2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.CheckConstraint('price >= 0', name='ck_services_price_nonnegative'))
    op.create_table('working_hours',
        sa.Column('id', sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('starts_at', sa.Time(), nullable=False),
        sa.Column('ends_at', sa.Time(), nullable=False),
        sa.CheckConstraint('weekday BETWEEN 0 AND 6', name='ck_working_hours_weekday'),
        sa.CheckConstraint('starts_at < ends_at', name='ck_working_hours_order'))
    op.create_table('days_off',
        sa.Column('id', sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column('day', sa.Date(), nullable=False, unique=True),
        sa.Column('reason', sa.String(200)))
    op.create_table('bookings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('service_id', sa.Integer(), sa.ForeignKey('services.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('price_snapshot', sa.Numeric(12,2), nullable=False),
        sa.Column('status', sa.String(20), server_default='confirmed', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("ends_at = starts_at + interval '1 hour'", name='ck_bookings_60_minutes'),
        sa.CheckConstraint('price_snapshot >= 0', name='ck_bookings_price_nonnegative'),
        sa.CheckConstraint("status IN ('confirmed','completed','cancelled','no_show')", name='ck_bookings_status'))
    # For one barber, any two non-cancelled time ranges must not overlap.
    # The [) range allows adjacent 10-11 and 11-12 appointments.
    op.execute("""ALTER TABLE bookings ADD CONSTRAINT ex_bookings_active_time
        EXCLUDE USING gist (tstzrange(starts_at, ends_at, '[)') WITH &&)
        WHERE (status IN ('confirmed','completed','no_show'))""")
    op.create_table('payments',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('booking_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bookings.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('amount', sa.Numeric(12,2), nullable=False),
        sa.Column('method', sa.String(12), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_payments_positive_amount'),
        sa.CheckConstraint("method IN ('cash','card')", name='ck_payments_method'))
    op.create_table('notifications',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('booking_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.UniqueConstraint('booking_id','kind',name='uq_notifications_booking_kind'),
        sa.CheckConstraint("kind IN ('reminder_24h','reminder_2h')", name='ck_notifications_kind'),
        sa.CheckConstraint("status IN ('pending','sending','sent','failed','cancelled')", name='ck_notifications_status'),
        sa.CheckConstraint('attempts >= 0', name='ck_notifications_attempts'))
    op.create_index('ix_notifications_due', 'notifications', ['status', 'scheduled_at'])
    op.create_index('ix_bookings_user_start', 'bookings', ['user_id','starts_at'])


def downgrade():
    op.drop_index('ix_bookings_user_start', table_name='bookings')
    op.drop_index('ix_notifications_due', table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('payments')
    op.drop_table('bookings')
    op.drop_table('days_off')
    op.drop_table('working_hours')
    op.drop_table('services')
    op.drop_table('users')

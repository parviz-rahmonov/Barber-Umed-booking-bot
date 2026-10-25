"""Seed internal booking marker for the simplified UI.

Revision ID: 0002_internal_service
Revises: 0001_initial
"""
from alembic import op
revision = '0002_internal_service'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("INSERT INTO services (name, price, is_active) VALUES ('Запись к мастеру', 0, true) ON CONFLICT (name) DO NOTHING")

def downgrade():
    # Preserve history: bookings may reference this internal row.
    pass

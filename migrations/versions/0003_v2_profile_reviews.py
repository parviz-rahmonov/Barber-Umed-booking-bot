"""V2.0: мастер и модерируемые отзывы.

Revision ID: 0003_v2_profile_reviews
Revises: 0002_internal_service
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_v2_profile_reviews'
down_revision = '0002_internal_service'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('barber_profile',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('phone', sa.String(32), nullable=False),
        sa.Column('address', sa.String(300), nullable=False))
    op.create_table('reviews',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('booking_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bookings.id', ondelete='RESTRICT'), nullable=False, unique=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(500), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_reviews_rating'))


def downgrade():
    op.drop_table('reviews')
    op.drop_table('barber_profile')

"""Exchange settlement: cash balances, reference prices, time in force

Revision ID: 3c1e5a9b7d20
Revises: ff5987b73cdb
Create Date: 2026-11-23 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3c1e5a9b7d20'
down_revision: Union[str, None] = 'ff5987b73cdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('cash_balance', sa.Float(), nullable=False, server_default='100000'))
    op.add_column('assets', sa.Column('reference_price', sa.Float(), nullable=True))
    op.add_column('assets', sa.Column('reference_price_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('time_in_force', sa.String(length=3), nullable=False, server_default='GTC'))


def downgrade() -> None:
    op.drop_column('orders', 'time_in_force')
    op.drop_column('assets', 'reference_price_at')
    op.drop_column('assets', 'reference_price')
    op.drop_column('users', 'cash_balance')

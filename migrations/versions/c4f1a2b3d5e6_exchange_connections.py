"""bóveda Fase B: tabla exchange_connections (sobre cifrado por usuario)

Revision ID: c4f1a2b3d5e6
Revises: 93c70347ec7c
Create Date: 2026-06-17 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4f1a2b3d5e6'
down_revision: Union[str, None] = '93c70347ec7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('exchange_connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('exchange', sa.String(length=32), server_default='binance', nullable=False),
        sa.Column('sealed', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('status_detail', sa.String(), nullable=True),
        sa.Column('last_verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'exchange', name='uq_exchange_user'),
    )
    op.create_index(op.f('ix_exchange_connections_user_id'),
                    'exchange_connections', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_exchange_connections_user_id'), table_name='exchange_connections')
    op.drop_table('exchange_connections')

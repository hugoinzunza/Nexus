"""auth: roles + identidad Google en users, tabla invitations

Revision ID: 93c70347ec7c
Revises: bf2b8271e2fa
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '93c70347ec7c'
down_revision: Union[str, None] = 'bf2b8271e2fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.String(length=16),
                                     server_default='beta', nullable=False))
    op.add_column('users', sa.Column('google_sub', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('picture', sa.String(), nullable=True))
    op.add_column('users', sa.Column('last_login', sa.DateTime(), nullable=True))
    op.create_unique_constraint('uq_users_google_sub', 'users', ['google_sub'])

    op.create_table('invitations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('invited_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )


def downgrade() -> None:
    op.drop_table('invitations')
    op.drop_constraint('uq_users_google_sub', 'users', type_='unique')
    op.drop_column('users', 'last_login')
    op.drop_column('users', 'picture')
    op.drop_column('users', 'google_sub')
    op.drop_column('users', 'role')

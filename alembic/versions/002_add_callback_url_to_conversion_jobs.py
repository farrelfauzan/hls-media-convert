"""add callback_url to conversion_jobs

Revision ID: 002
Revises: 001
Create Date: 2026-03-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversion_jobs',
        sa.Column('callback_url', sa.String(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('conversion_jobs', 'callback_url')

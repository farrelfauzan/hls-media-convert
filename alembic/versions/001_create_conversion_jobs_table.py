"""create conversion jobs table

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversion_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('celery_task_id', sa.String(255), nullable=True, index=True),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('source_s3_key', sa.String(512), nullable=False),
        sa.Column('output_s3_prefix', sa.String(512), nullable=True),
        sa.Column('master_playlist_url', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='jobstatus'), nullable=False, default='pending', index=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('conversion_jobs')
    op.execute('DROP TYPE IF EXISTS jobstatus')

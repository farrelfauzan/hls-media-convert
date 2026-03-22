"""create webhook_logs table

Revision ID: 003
Revises: 002
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False, index=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("method", sa.String(10), nullable=False, server_default="POST"),
        sa.Column("request_headers", sa.Text, nullable=True),
        sa.Column("request_body", sa.Text, nullable=True),
        sa.Column("response_status_code", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("webhook_logs")

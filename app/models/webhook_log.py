from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.sql import func

from app.models.job import Base


class WebhookLog(Base):
    """Database model for tracking webhook delivery attempts"""

    __tablename__ = "webhook_logs"

    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), nullable=False, index=True)

    # Request details
    url = Column(String(1024), nullable=False)
    method = Column(String(10), nullable=False, default="POST")
    request_headers = Column(Text, nullable=True)
    request_body = Column(Text, nullable=True)

    # Response details
    response_status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)

    # Outcome
    status = Column(String(20), nullable=False, index=True)  # "success", "failed", "no_url"
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

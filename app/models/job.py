from sqlalchemy import Column, String, DateTime, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ConversionJob(Base):
    """Database model for tracking conversion jobs"""
    
    __tablename__ = "conversion_jobs"
    
    id = Column(String(36), primary_key=True)
    celery_task_id = Column(String(255), nullable=True, index=True)
    
    # Source video info
    original_filename = Column(String(255), nullable=False)
    source_s3_key = Column(String(512), nullable=False)
    
    # Output info
    output_s3_prefix = Column(String(512), nullable=True)
    master_playlist_url = Column(Text, nullable=True)
    
    # Webhook
    callback_url = Column(String(1024), nullable=True)
    
    # Status tracking
    status = Column(
        SQLEnum(JobStatus),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<ConversionJob(id={self.id}, status={self.status})>"

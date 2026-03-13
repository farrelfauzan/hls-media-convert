from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Request schemas
class UploadRequestSchema(BaseModel):
    """Request schema for getting presigned upload URL"""
    filename: str = Field(..., description="Name of the file to upload")
    content_type: str = Field(..., description="MIME type of the file")


class ConversionRequestSchema(BaseModel):
    """Request schema for starting a conversion"""
    s3_key: str = Field(..., description="S3 key of the uploaded video")
    original_filename: str = Field(..., description="Original filename")


# Response schemas
class PresignedUploadResponse(BaseModel):
    """Response schema for presigned upload URL"""
    upload_url: str = Field(..., description="URL to upload the file")
    fields: dict = Field(..., description="Form fields to include in upload")
    s3_key: str = Field(..., description="S3 key where file will be stored")
    expires_in: int = Field(..., description="URL expiration in seconds")


class JobResponse(BaseModel):
    """Response schema for job information"""
    job_id: str = Field(..., validation_alias="id", description="Unique job identifier")
    status: JobStatus = Field(..., description="Current job status")
    original_filename: str = Field(..., description="Original filename")
    source_s3_key: str = Field(..., description="Source video S3 key")
    output_s3_prefix: Optional[str] = Field(None, description="Output HLS S3 prefix")
    master_playlist_url: Optional[str] = Field(None, description="Master playlist URL")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    created_at: Optional[datetime] = Field(None, description="Job creation time")
    completed_at: Optional[datetime] = Field(None, description="Job completion time")
    
    class Config:
        from_attributes = True
        populate_by_name = True


class JobListResponse(BaseModel):
    """Response schema for list of jobs"""
    jobs: List[JobResponse]
    total: int
    page: int
    page_size: int


class TaskStatusResponse(BaseModel):
    """Response schema for Celery task status"""
    task_id: str
    status: str
    progress: Optional[int] = None
    result: Optional[dict] = None


class ConversionStartResponse(BaseModel):
    """Response schema when conversion is started"""
    job_id: str = Field(..., description="Job identifier")
    task_id: str = Field(..., description="Celery task identifier")
    status: str = Field(..., description="Initial status")
    message: str = Field(..., description="Status message")


class HealthResponse(BaseModel):
    """Response schema for health check"""
    status: str
    version: str
    services: dict


class ErrorResponse(BaseModel):
    """Response schema for errors"""
    error: str
    detail: Optional[str] = None

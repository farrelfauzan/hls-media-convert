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


class WebhookPayload(BaseModel):
    """Schema describing the webhook payload sent to the callback URL.

    This is not used in any request/response — it exists for Swagger documentation only.
    """
    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(..., description="Conversion result: 'completed' or 'failed'")
    master_playlist_url: Optional[str] = Field(None, description="Public URL of the HLS master playlist (present when status is 'completed')")
    error_message: Optional[str] = Field(None, description="Error details (present when status is 'failed')")

    model_config = {"json_schema_extra": {"examples": [
        {"job_id": "a1b2c3", "status": "completed", "master_playlist_url": "https://s3.amazonaws.com/bucket/hls/a1b2c3/master.m3u8", "error_message": None},
        {"job_id": "a1b2c3", "status": "failed", "master_playlist_url": None, "error_message": "FFmpeg conversion failed"},
    ]}}


class BulkUploadRequestItem(BaseModel):
    """Single item in a bulk upload request"""
    filename: str = Field(..., description="Name of the file to upload")
    content_type: str = Field(..., description="MIME type of the file")


class BulkUploadRequestSchema(BaseModel):
    """Request schema for getting multiple presigned upload URLs"""
    files: List[BulkUploadRequestItem] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of files to get presigned upload URLs for (max 50)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "files": [
                        {"filename": "video1.mp4", "content_type": "video/mp4"},
                        {"filename": "video2.mov", "content_type": "video/quicktime"},
                    ]
                }
            ]
        }
    }


class BulkUploadResponseItem(BaseModel):
    """Single item in a bulk upload response"""
    filename: str = Field(..., description="Original filename")
    upload_url: str = Field(..., description="URL to upload the file")
    fields: dict = Field(..., description="Form fields to include in upload")
    s3_key: str = Field(..., description="S3 key where file will be stored")
    expires_in: int = Field(..., description="URL expiration in seconds")
    error: Optional[str] = Field(None, description="Error message if URL generation failed")


class BulkUploadResponse(BaseModel):
    """Response schema for bulk presigned upload URLs"""
    results: List[BulkUploadResponseItem] = Field(..., description="Presigned URL results per file")
    total: int = Field(..., description="Total number of files requested")
    succeeded: int = Field(..., description="Number of URLs successfully generated")
    failed: int = Field(..., description="Number of URLs that failed to generate")


class BulkConversionRequestItem(BaseModel):
    """Single item in a bulk conversion request"""
    s3_key: str = Field(..., description="S3 key of the uploaded video")
    original_filename: str = Field(..., description="Original filename")
    callback_url: Optional[str] = Field(
        None,
        description="Webhook URL called when this job completes or fails",
        json_schema_extra={"example": "https://your-api.com/webhooks/hls-conversion"},
    )


class BulkConversionRequestSchema(BaseModel):
    """Request schema for starting multiple conversions"""
    conversions: List[BulkConversionRequestItem] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of videos to convert (max 50)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "conversions": [
                        {
                            "s3_key": "uploads/abc123.mp4",
                            "original_filename": "video1.mp4",
                            "callback_url": "https://your-api.com/webhooks/hls-conversion",
                        },
                        {
                            "s3_key": "uploads/def456.mov",
                            "original_filename": "video2.mov",
                        },
                    ]
                }
            ]
        }
    }


class BulkConversionResponseItem(BaseModel):
    """Single item in a bulk conversion response"""
    s3_key: str = Field(..., description="Source S3 key")
    original_filename: str = Field(..., description="Original filename")
    job_id: Optional[str] = Field(None, description="Job identifier (null on failure)")
    task_id: Optional[str] = Field(None, description="Celery task identifier (null on failure)")
    status: str = Field(..., description="'processing' or 'failed'")
    message: str = Field(..., description="Status or error message")


class BulkConversionResponse(BaseModel):
    """Response schema when multiple conversions are started"""
    results: List[BulkConversionResponseItem] = Field(..., description="Conversion result per item")
    total: int = Field(..., description="Total number of conversions requested")
    succeeded: int = Field(..., description="Number of jobs successfully queued")
    failed: int = Field(..., description="Number of jobs that failed to queue")


class ConversionRequestSchema(BaseModel):
    """Request schema for starting a conversion"""
    s3_key: str = Field(..., description="S3 key of the uploaded video")
    original_filename: str = Field(..., description="Original filename")
    callback_url: Optional[str] = Field(
        None,
        description=(
            "Webhook URL that will receive a POST request when the conversion completes or fails. "
            "The payload is JSON with fields: `job_id`, `status` ('completed' | 'failed'), "
            "`master_playlist_url` (on success), and `error_message` (on failure). "
            "If a WEBHOOK_SECRET is configured, the request includes an `X-Webhook-Signature` header "
            "containing an HMAC-SHA256 hex digest of the sorted JSON body."
        ),
        json_schema_extra={"example": "https://your-api.com/webhooks/hls-conversion"},
    )


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

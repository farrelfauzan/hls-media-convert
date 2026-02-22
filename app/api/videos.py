import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from celery.result import AsyncResult

from app.core.config import settings
from app.core.database import get_db
from app.models.job import ConversionJob, JobStatus
from app.schemas.job import (
    UploadRequestSchema,
    PresignedUploadResponse,
    ConversionRequestSchema,
    ConversionStartResponse,
    JobResponse,
    JobListResponse,
    TaskStatusResponse,
    ErrorResponse,
)
from app.services.s3_service import s3_service
from app.tasks.conversion_tasks import convert_video_to_hls
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/videos", tags=["videos"])


def validate_file_extension(filename: str) -> bool:
    """Validate that file has an allowed extension"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in settings.ALLOWED_EXTENSIONS


@router.post(
    "/upload-url",
    response_model=PresignedUploadResponse,
    summary="Get presigned URL for video upload",
    description="Generate a presigned URL for uploading a video file directly to S3",
)
async def get_upload_url(request: UploadRequestSchema):
    """
    Generate a presigned URL for uploading a video to S3.
    
    The client can use this URL to upload the video directly to S3
    without going through the API server.
    """
    # Validate file extension
    if not validate_file_extension(request.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {settings.ALLOWED_EXTENSIONS}",
        )
    
    # Generate unique S3 key
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(request.filename)[1]
    s3_key = f"uploads/{file_id}{ext}"
    
    # Generate presigned URL
    try:
        presigned_data = s3_service.generate_presigned_upload_url(
            s3_key=s3_key,
            content_type=request.content_type,
            expiration=3600,  # 1 hour
        )
        
        return PresignedUploadResponse(
            upload_url=presigned_data["url"],
            fields=presigned_data["fields"],
            s3_key=s3_key,
            expires_in=3600,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate upload URL: {str(e)}",
        )


@router.post(
    "/convert",
    response_model=ConversionStartResponse,
    summary="Start video conversion",
    description="Start converting an uploaded video to HLS format",
)
async def start_conversion(
    request: ConversionRequestSchema,
    db: AsyncSession = Depends(get_db),
):
    """
    Start a video conversion job.
    
    The video must already be uploaded to S3. This endpoint creates
    a conversion job and queues it for background processing.
    """
    # Verify the source file exists
    if not s3_service.file_exists(request.s3_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source video not found in S3",
        )
    
    # Create job record
    job_id = str(uuid.uuid4())
    output_s3_prefix = f"hls/{job_id}"
    
    job = ConversionJob(
        id=job_id,
        original_filename=request.original_filename,
        source_s3_key=request.s3_key,
        output_s3_prefix=output_s3_prefix,
        status=JobStatus.PENDING,
    )
    
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    # Queue Celery task
    task = convert_video_to_hls.delay(
        job_id=job_id,
        source_s3_key=request.s3_key,
        output_s3_prefix=output_s3_prefix,
        original_filename=request.original_filename,
    )
    
    # Update job with task ID
    job.celery_task_id = task.id
    job.status = JobStatus.PROCESSING
    await db.commit()
    
    return ConversionStartResponse(
        job_id=job_id,
        task_id=task.id,
        status="processing",
        message="Conversion job has been queued",
    )


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="List conversion jobs",
    description="Get a paginated list of conversion jobs",
)
async def list_jobs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a list of all conversion jobs with pagination.
    """
    # Build query
    query = select(ConversionJob).order_by(ConversionJob.created_at.desc())
    count_query = select(func.count(ConversionJob.id))
    
    if status_filter:
        try:
            status_enum = JobStatus(status_filter)
            query = query.where(ConversionJob.status == status_enum)
            count_query = count_query.where(ConversionJob.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Valid values: {[s.value for s in JobStatus]}",
            )
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    # Execute query
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    return JobListResponse(
        jobs=[JobResponse.model_validate(job) for job in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get job details",
    description="Get detailed information about a conversion job",
)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a specific conversion job.
    """
    result = await db.execute(
        select(ConversionJob).where(ConversionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    return JobResponse.model_validate(job)


@router.get(
    "/jobs/{job_id}/status",
    response_model=TaskStatusResponse,
    summary="Get job task status",
    description="Get the Celery task status for a job",
)
async def get_job_task_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the real-time status of the Celery task for a job.
    """
    # Get job
    result = await db.execute(
        select(ConversionJob).where(ConversionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    if not job.celery_task_id:
        return TaskStatusResponse(
            task_id="",
            status=job.status.value,
            progress=0 if job.status == JobStatus.PENDING else 100,
            result=None,
        )
    
    # Get Celery task status
    task_result = AsyncResult(job.celery_task_id, app=celery_app)
    
    response = TaskStatusResponse(
        task_id=job.celery_task_id,
        status=task_result.status,
        progress=None,
        result=None,
    )
    
    if task_result.info:
        if isinstance(task_result.info, dict):
            response.progress = task_result.info.get("progress")
            if task_result.status == "SUCCESS":
                response.result = task_result.info
    
    return response


@router.delete(
    "/jobs/{job_id}",
    summary="Delete a job",
    description="Delete a job and its associated HLS files from S3",
)
async def delete_job(
    job_id: str,
    delete_s3_files: bool = Query(True, description="Also delete S3 files"),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a conversion job and optionally its S3 files.
    """
    # Get job
    result = await db.execute(
        select(ConversionJob).where(ConversionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    # Delete S3 files if requested
    if delete_s3_files and job.output_s3_prefix:
        try:
            s3_service.delete_folder(job.output_s3_prefix)
        except Exception as e:
            # Log but don't fail if S3 deletion fails
            pass
    
    # Delete job from database
    await db.delete(job)
    await db.commit()
    
    return {"message": "Job deleted successfully", "job_id": job_id}


@router.get(
    "/stream/{job_id}",
    summary="Get stream URL",
    description="Get the HLS stream URL for a completed job",
)
async def get_stream_url(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the master playlist URL for streaming a converted video.
    """
    result = await db.execute(
        select(ConversionJob).where(ConversionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is not completed. Current status: {job.status.value}",
        )
    
    if not job.master_playlist_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stream URL not available",
        )
    
    return {
        "job_id": job_id,
        "stream_url": job.master_playlist_url,
        "status": job.status.value,
    }

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
    BulkUploadRequestSchema,
    BulkUploadResponse,
    BulkUploadResponseItem,
    BulkConversionRequestSchema,
    BulkConversionResponse,
    BulkConversionResponseItem,
)
from app.services.s3_service import s3_service
from app.tasks.conversion_tasks import convert_video_to_hls
from app.tasks.celery_app import celery_app
from app.core.auth import require_api_key

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[Depends(require_api_key)])


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
    s3_key = f"videos/{file_id}{ext}"
    
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
    "/bulk-upload-urls",
    response_model=BulkUploadResponse,
    summary="Get presigned URLs for bulk video upload",
    description=(
        "Generate presigned S3 upload URLs for multiple video files in a single request. "
        "Accepts up to **50** files. Each item in `results` independently reports success or failure, "
        "so a partial success is possible."
    ),
    responses={
        200: {"description": "Presigned URLs generated (check per-item `error` field for partial failures)"},
        422: {"description": "Validation error"},
    },
)
async def bulk_get_upload_urls(request: BulkUploadRequestSchema):
    """
    Generate presigned S3 upload URLs for multiple files at once.

    Each file is processed independently — if one fails (e.g. unsupported extension)
    only that item will contain an `error`; the others will succeed.

    After uploading all files, use `/videos/bulk-convert` to start conversions.
    """
    results: list[BulkUploadResponseItem] = []
    succeeded = 0
    failed = 0

    for item in request.files:
        if not validate_file_extension(item.filename):
            results.append(
                BulkUploadResponseItem(
                    filename=item.filename,
                    upload_url="",
                    fields={},
                    s3_key="",
                    expires_in=0,
                    error=f"Invalid file type. Allowed types: {settings.ALLOWED_EXTENSIONS}",
                )
            )
            failed += 1
            continue

        file_id = str(uuid.uuid4())
        ext = os.path.splitext(item.filename)[1]
        s3_key = f"videos/{file_id}{ext}"

        try:
            presigned_data = s3_service.generate_presigned_upload_url(
                s3_key=s3_key,
                content_type=item.content_type,
                expiration=3600,
            )
            results.append(
                BulkUploadResponseItem(
                    filename=item.filename,
                    upload_url=presigned_data["url"],
                    fields=presigned_data["fields"],
                    s3_key=s3_key,
                    expires_in=3600,
                )
            )
            succeeded += 1
        except Exception as e:
            results.append(
                BulkUploadResponseItem(
                    filename=item.filename,
                    upload_url="",
                    fields={},
                    s3_key="",
                    expires_in=0,
                    error=f"Failed to generate upload URL: {str(e)}",
                )
            )
            failed += 1

    return BulkUploadResponse(
        results=results,
        total=len(request.files),
        succeeded=succeeded,
        failed=failed,
    )


@router.post(
    "/bulk-convert",
    response_model=BulkConversionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start bulk video conversion",
    description=(
        "Queue HLS conversion jobs for multiple already-uploaded videos in a single request. "
        "Accepts up to **50** items. Each item is processed independently."
    ),
    responses={
        202: {"description": "Jobs accepted (check per-item `status` for partial failures)"},
        422: {"description": "Validation error"},
    },
)
async def bulk_start_conversion(
    request: BulkConversionRequestSchema,
    db: AsyncSession = Depends(get_db),
):
    """
    Start HLS conversion jobs for multiple videos.

    Each video must already exist in S3. Jobs that pass S3 existence checks are
    immediately queued; items that fail (missing file, DB error, etc.) report
    `status: "failed"` in the response while the others proceed normally.

    ## Webhook
    Per-item `callback_url` behaves identically to the single `/convert` endpoint.
    """
    results: list[BulkConversionResponseItem] = []
    succeeded = 0
    failed = 0

    for item in request.conversions:
        # Verify source file exists in S3
        if not s3_service.file_exists(item.s3_key):
            results.append(
                BulkConversionResponseItem(
                    s3_key=item.s3_key,
                    original_filename=item.original_filename,
                    status="failed",
                    message="Source video not found in S3",
                )
            )
            failed += 1
            continue

        try:
            job_id = str(uuid.uuid4())
            output_s3_prefix = f"hls/{job_id}"

            job = ConversionJob(
                id=job_id,
                original_filename=item.original_filename,
                source_s3_key=item.s3_key,
                output_s3_prefix=output_s3_prefix,
                callback_url=item.callback_url,
                status=JobStatus.PENDING,
            )
            db.add(job)
            await db.flush()  # get DB row before committing batch

            task = convert_video_to_hls.delay(
                job_id=job_id,
                source_s3_key=item.s3_key,
                output_s3_prefix=output_s3_prefix,
                original_filename=item.original_filename,
                callback_url=item.callback_url,
            )

            job.celery_task_id = task.id
            job.status = JobStatus.PROCESSING

            results.append(
                BulkConversionResponseItem(
                    s3_key=item.s3_key,
                    original_filename=item.original_filename,
                    job_id=job_id,
                    task_id=task.id,
                    status="processing",
                    message="Conversion job has been queued",
                )
            )
            succeeded += 1
        except Exception as e:
            results.append(
                BulkConversionResponseItem(
                    s3_key=item.s3_key,
                    original_filename=item.original_filename,
                    status="failed",
                    message=f"Failed to queue conversion: {str(e)}",
                )
            )
            failed += 1

    await db.commit()

    return BulkConversionResponse(
        results=results,
        total=len(request.conversions),
        succeeded=succeeded,
        failed=failed,
    )


@router.post(
    "/convert",
    response_model=ConversionStartResponse,
    summary="Start video conversion",
    description="Start converting an uploaded video to HLS format. "
    "Optionally provide a `callback_url` to receive a webhook POST when the job finishes.",
)
async def start_conversion(
    request: ConversionRequestSchema,
    db: AsyncSession = Depends(get_db),
):
    """
    Start a video conversion job.

    The video must already be uploaded to S3. This endpoint creates
    a conversion job and queues it for background processing.

    ## Webhook (callback_url)

    If `callback_url` is provided, the service will send a **POST** request
    to that URL when the conversion **completes** or **fails**.

    **Payload:**
    ```json
    {
      "job_id": "<uuid>",
      "status": "completed" | "failed",
      "master_playlist_url": "https://..." | null,
      "error_message": "..." | null
    }
    ```

    **Signature verification (optional):**
    If `WEBHOOK_SECRET` is configured, the request includes an
    `X-Webhook-Signature` header with an HMAC-SHA256 hex digest
    of the JSON body (keys sorted).
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
        callback_url=request.callback_url,
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
        callback_url=request.callback_url,
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


@router.get(
    "/playlists",
    summary="List HLS playlists",
    description="Retrieve all M3U8 playlists or search by filename",
)
async def list_playlists(
    search: Optional[str] = Query(None, description="Search by original filename"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all completed jobs that have an M3U8 master playlist URL.
    Optionally filter by original filename using the `search` query param.
    """
    query = (
        select(ConversionJob)
        .where(
            ConversionJob.status == JobStatus.COMPLETED,
            ConversionJob.master_playlist_url.isnot(None),
        )
        .order_by(ConversionJob.created_at.desc())
    )
    count_query = (
        select(func.count(ConversionJob.id))
        .where(
            ConversionJob.status == JobStatus.COMPLETED,
            ConversionJob.master_playlist_url.isnot(None),
        )
    )

    if search:
        like_expr = f"%{search}%"
        query = query.where(ConversionJob.original_filename.ilike(like_expr))
        count_query = count_query.where(ConversionJob.original_filename.ilike(like_expr))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    jobs = result.scalars().all()

    return {
        "playlists": [
            {
                "job_id": job.id,
                "original_filename": job.original_filename,
                "master_playlist_url": job.master_playlist_url,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
            }
            for job in jobs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }

import os
import uuid
import logging
from datetime import datetime
from typing import Optional
from celery import states
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.tasks.celery_app import celery_app
from app.services.s3_service import s3_service
from app.services.hls_service import hls_converter
from app.services.webhook_service import send_webhook_sync
from app.core.config import settings
from app.models.job import ConversionJob, JobStatus

logger = logging.getLogger(__name__)

# Create sync engine for Celery tasks (Celery doesn't support async)
sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
sync_engine = create_engine(sync_db_url)
SyncSession = sessionmaker(bind=sync_engine)


def update_job_status(
    job_id: str,
    status: JobStatus,
    master_playlist_url: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update job status in database"""
    session = SyncSession()
    try:
        job = session.query(ConversionJob).filter(ConversionJob.id == job_id).first()
        if job:
            job.status = status
            if master_playlist_url:
                job.master_playlist_url = master_playlist_url
            if error_message:
                job.error_message = error_message
            if status in (JobStatus.COMPLETED, JobStatus.FAILED):
                job.completed_at = datetime.utcnow()
            session.commit()
            logger.info(f"Updated job {job_id} status to {status.value}")
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
        session.rollback()
    finally:
        session.close()


@celery_app.task(bind=True, name="convert_video_to_hls")
def convert_video_to_hls(
    self,
    job_id: str,
    source_s3_key: str,
    output_s3_prefix: str,
    original_filename: str,
    callback_url: Optional[str] = None,
) -> dict:
    """
    Celery task to convert a video from S3 to HLS format and upload back to S3
    
    Args:
        job_id: Unique job identifier
        source_s3_key: S3 key of the source video
        output_s3_prefix: S3 prefix for HLS output
        original_filename: Original filename for reference
        
    Returns:
        Dictionary with conversion results
    """
    local_video_path = None
    local_output_dir = None
    
    try:
        logger.info(f"[JOB {job_id}] Task started. source={source_s3_key}, callback_url={callback_url}")
        
        # Update task state
        self.update_state(
            state="PROCESSING",
            meta={
                "job_id": job_id,
                "status": "downloading",
                "progress": 10,
            }
        )
        
        # Create temp directories
        local_video_path = os.path.join(settings.TEMP_DIR, job_id, original_filename)
        local_output_dir = os.path.join(settings.TEMP_DIR, job_id, "hls_output")
        os.makedirs(os.path.dirname(local_video_path), exist_ok=True)
        
        # Download video from S3
        logger.info(f"[JOB {job_id}] Downloading video from S3: {source_s3_key}")
        s3_service.download_file(source_s3_key, local_video_path)
        logger.info(f"[JOB {job_id}] Download complete. File size: {os.path.getsize(local_video_path)} bytes")
        
        # Update task state
        self.update_state(
            state="PROCESSING",
            meta={
                "job_id": job_id,
                "status": "converting",
                "progress": 30,
            }
        )
        
        # Convert to HLS
        logger.info(f"[JOB {job_id}] Starting HLS conversion: {local_video_path}")
        hls_result = hls_converter.convert_to_hls(
            video_path=local_video_path,
            output_dir=local_output_dir,
            job_id=job_id,
        )
        logger.info(f"[JOB {job_id}] HLS conversion complete. Output dir: {hls_result.output_dir}")
        
        # Update task state
        self.update_state(
            state="PROCESSING",
            meta={
                "job_id": job_id,
                "status": "uploading",
                "progress": 70,
            }
        )
        
        # Upload HLS files to S3
        logger.info(f"[JOB {job_id}] Uploading HLS files to S3: {output_s3_prefix}")
        uploaded_files = upload_hls_to_s3(
            hls_result.output_dir,
            output_s3_prefix,
        )
        logger.info(f"[JOB {job_id}] Upload complete. {len(uploaded_files)} files uploaded")
        
        # Generate master playlist URL
        master_playlist_url = s3_service.get_public_url(
            f"{output_s3_prefix}/master.m3u8"
        )
        
        # Cleanup local files
        cleanup_local_files(job_id)
        
        # Update job status in database
        logger.info(f"[JOB {job_id}] Updating DB status to COMPLETED. playlist_url={master_playlist_url}")
        update_job_status(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            master_playlist_url=master_playlist_url,
        )
        logger.info(f"[JOB {job_id}] DB updated successfully")
        
        # Send webhook notification
        webhook_url = callback_url or settings.WEBHOOK_URL
        logger.info(f"[JOB {job_id}] Sending webhook to: {webhook_url}")
        send_webhook_sync(
            callback_url=callback_url,
            job_id=job_id,
            status="completed",
            master_playlist_url=master_playlist_url,
        )
        logger.info(f"[JOB {job_id}] Conversion fully complete. Master playlist: {master_playlist_url}")
        
        return {
            "job_id": job_id,
            "status": "completed",
            "master_playlist_url": master_playlist_url,
            "output_s3_prefix": output_s3_prefix,
            "uploaded_files_count": len(uploaded_files),
        }
        
    except Exception as e:
        logger.error(f"[JOB {job_id}] Conversion FAILED: {str(e)}", exc_info=True)
        
        # Update job status in database
        update_job_status(
            job_id=job_id,
            status=JobStatus.FAILED,
            error_message=str(e),
        )
        
        # Send webhook notification
        send_webhook_sync(
            callback_url=callback_url,
            job_id=job_id,
            status="failed",
            error_message=str(e),
        )
        
        # Cleanup on failure
        cleanup_local_files(job_id)
        
        # Re-raise to mark task as failed
        self.update_state(
            state=states.FAILURE,
            meta={
                "job_id": job_id,
                "status": "failed",
                "error": str(e),
            }
        )
        raise


def upload_hls_to_s3(local_dir: str, s3_prefix: str) -> list:
    """
    Upload all HLS files from local directory to S3
    
    Args:
        local_dir: Local directory containing HLS files
        s3_prefix: S3 prefix for uploads
        
    Returns:
        List of uploaded S3 keys
    """
    uploaded_files = []
    
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            local_path = os.path.join(root, file)
            
            # Calculate relative path from local_dir
            relative_path = os.path.relpath(local_path, local_dir)
            s3_key = f"{s3_prefix}/{relative_path}"
            
            # Determine content type
            content_type = get_content_type(file)
            
            # Upload to S3
            s3_service.upload_file(
                local_path,
                s3_key,
                content_type=content_type,
            )
            
            uploaded_files.append(s3_key)
            logger.debug(f"Uploaded: {s3_key}")
    
    return uploaded_files


def get_content_type(filename: str) -> str:
    """
    Get content type based on file extension
    
    Args:
        filename: Name of the file
        
    Returns:
        Content type string
    """
    extension = os.path.splitext(filename)[1].lower()
    
    content_types = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }
    
    return content_types.get(extension, "application/octet-stream")


def cleanup_local_files(job_id: str) -> None:
    """
    Clean up local temporary files for a job
    
    Args:
        job_id: Job identifier
    """
    import shutil
    
    job_dir = os.path.join(settings.TEMP_DIR, job_id)
    if os.path.exists(job_dir):
        try:
            shutil.rmtree(job_dir)
            logger.info(f"Cleaned up local files for job: {job_id}")
        except Exception as e:
            logger.warning(f"Failed to cleanup local files for job {job_id}: {e}")


@celery_app.task(bind=True, name="delete_hls_from_s3")
def delete_hls_from_s3(self, s3_prefix: str) -> dict:
    """
    Delete HLS files from S3
    
    Args:
        s3_prefix: S3 prefix to delete
        
    Returns:
        Dictionary with deletion results
    """
    try:
        s3_service.delete_folder(s3_prefix)
        return {
            "status": "deleted",
            "s3_prefix": s3_prefix,
        }
    except Exception as e:
        logger.error(f"Failed to delete HLS files: {str(e)}")
        raise

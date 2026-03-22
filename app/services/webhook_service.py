import hashlib
import hmac
import json
import logging
import uuid
from typing import Optional

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

# Sync DB session for use inside Celery tasks
_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)
_SyncSession = sessionmaker(bind=_sync_engine)


def _save_webhook_log(
    job_id: str,
    url: str,
    request_headers: Optional[str],
    request_body: Optional[str],
    response_status_code: Optional[int],
    response_body: Optional[str],
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Persist a webhook delivery attempt to the database."""
    from app.models.webhook_log import WebhookLog

    session = _SyncSession()
    try:
        log = WebhookLog(
            id=str(uuid.uuid4()),
            job_id=job_id,
            url=url,
            method="POST",
            request_headers=request_headers,
            request_body=request_body,
            response_status_code=response_status_code,
            response_body=response_body,
            status=status,
            error_message=error_message,
        )
        session.add(log)
        session.commit()
    except Exception as e:
        logger.error(f"Failed to save webhook log for job {job_id}: {e}")
        session.rollback()
    finally:
        session.close()


def send_webhook_sync(
    callback_url: Optional[str],
    job_id: str,
    status: str,
    master_playlist_url: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Send a webhook notification (synchronous, for use inside Celery tasks).

    Uses the per-job callback_url if provided, otherwise falls back to the
    global WEBHOOK_URL from settings.
    """
    url = callback_url or settings.WEBHOOK_URL
    if not url:
        logger.debug("No webhook URL configured, skipping notification")
        _save_webhook_log(
            job_id=job_id,
            url="(none)",
            request_headers=None,
            request_body=None,
            response_status_code=None,
            response_body=None,
            status="no_url",
            error_message="No webhook URL configured (neither callback_url nor WEBHOOK_URL)",
        )
        return

    payload = {
        "job_id": job_id,
        "status": status,
        "master_playlist_url": master_playlist_url,
        "error_message": error_message,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}

    if settings.WEBHOOK_SECRET:
        body = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            settings.WEBHOOK_SECRET.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["X-Webhook-Signature"] = signature

    request_body_str = json.dumps(payload, indent=2)
    request_headers_str = json.dumps(headers)

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        logger.info(f"Webhook sent successfully for job {job_id} to {url}")
        _save_webhook_log(
            job_id=job_id,
            url=url,
            request_headers=request_headers_str,
            request_body=request_body_str,
            response_status_code=response.status_code,
            response_body=response.text[:4000] if response.text else None,
            status="success",
        )
    except Exception as e:
        logger.error(f"Failed to send webhook for job {job_id} to {url}: {e}")
        resp_code = getattr(getattr(e, "response", None), "status_code", None)
        resp_body = None
        if hasattr(e, "response") and e.response is not None:
            try:
                resp_body = e.response.text[:4000]
            except Exception:
                pass
        _save_webhook_log(
            job_id=job_id,
            url=url,
            request_headers=request_headers_str,
            request_body=request_body_str,
            response_status_code=resp_code,
            response_body=resp_body,
            status="failed",
            error_message=str(e)[:4000],
        )

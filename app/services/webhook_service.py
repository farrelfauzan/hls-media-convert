import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


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

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        logger.info(f"Webhook sent successfully for job {job_id} to {url}")
    except Exception as e:
        logger.error(f"Failed to send webhook for job {job_id} to {url}: {e}")

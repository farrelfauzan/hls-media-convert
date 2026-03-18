from pydantic_settings import BaseSettings
from typing import List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    # App settings
    APP_NAME: str = "HLS Video Converter"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hls_converter"
    
    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = ""
    S3_ENDPOINT_URL: Optional[str] = None  # For MinIO or LocalStack
    
    # HLS Settings
    HLS_SEGMENT_DURATION: int = 6  # seconds
    HLS_PLAYLIST_TYPE: str = "vod"
    
    # Multi-bitrate profiles (resolution, video_bitrate, audio_bitrate)
    HLS_PROFILES: List[dict] = [
        {"name": "360p", "width": 640, "height": 360, "video_bitrate": "800k", "audio_bitrate": "96k"},
        {"name": "480p", "width": 854, "height": 480, "video_bitrate": "1400k", "audio_bitrate": "128k"},
        {"name": "720p", "width": 1280, "height": 720, "video_bitrate": "2800k", "audio_bitrate": "128k"},
        {"name": "1080p", "width": 1920, "height": 1080, "video_bitrate": "5000k", "audio_bitrate": "192k"},
    ]
    
    # Temp directory for processing
    TEMP_DIR: str = "/tmp/hls_converter"
    
    # Webhook
    WEBHOOK_URL: str = ""  # Default webhook URL for conversion notifications
    WEBHOOK_SECRET: str = ""  # HMAC secret for webhook signature verification
    
    # Allowed video extensions
    ALLOWED_EXTENSIONS: List[str] = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"]
    
    # Max file size (in bytes) - 5GB default
    MAX_FILE_SIZE: int = 5 * 1024 * 1024 * 1024
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

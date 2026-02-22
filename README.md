# HLS Video Converter API

A FastAPI-based service for converting video files to HLS (HTTP Live Streaming) format with multi-bitrate support. Uses Celery for background processing and AWS S3 for storage.

## Features

- Convert MP4, MOV, AVI, MKV, WebM, FLV, WMV to HLS
- Multi-bitrate adaptive streaming (360p, 480p, 720p, 1080p)
- Background processing with Celery
- Direct S3 upload using presigned URLs
- Job tracking with PostgreSQL
- Docker-ready deployment

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│  FastAPI    │────▶│   Celery    │
│  (Upload)   │     │    API      │     │   Worker    │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │ PostgreSQL  │     │    Redis    │
                    │  (Jobs DB)  │     │  (Broker)   │
                    └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   AWS S3    │
                                        │  (Storage)  │
                                        └─────────────┘
```

## Flow

1. Client requests presigned upload URL
2. Client uploads video directly to S3
3. Client triggers conversion via API
4. Celery worker downloads video, converts to HLS, uploads to S3
5. Client polls for job status
6. Client gets HLS stream URL for playback

## Quick Start

### Using Docker Compose (Recommended)

1. Clone the repository and create environment file:

```bash
cp .env.example .env
# Edit .env with your AWS credentials
```

2. For local development with MinIO (S3-compatible):

```bash
# Start all services including MinIO
docker-compose --profile local up -d

# Update .env for MinIO
export S3_ENDPOINT_URL=http://localhost:9000
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
export S3_BUCKET_NAME=hls-videos
```

3. For production with AWS S3:

```bash
# Start services without MinIO
docker-compose up -d
```

4. Access the API at `http://localhost:8000`
5. API documentation at `http://localhost:8000/docs`

### Local Development

1. Install dependencies:

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

2. Install FFmpeg:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

3. Start Redis and PostgreSQL (or use Docker):

```bash
docker-compose up -d db redis
```

4. Run the API:

```bash
uvicorn app.main:app --reload
```

5. Run the Celery worker:

```bash
celery -A app.tasks.celery_app worker --loglevel=info
```

## API Endpoints

### Get Upload URL
```bash
POST /api/v1/videos/upload-url
{
  "filename": "my_video.mp4",
  "content_type": "video/mp4"
}
```

Response:
```json
{
  "upload_url": "https://...",
  "fields": {...},
  "s3_key": "uploads/uuid.mp4",
  "expires_in": 3600
}
```

### Start Conversion
```bash
POST /api/v1/videos/convert
{
  "s3_key": "uploads/uuid.mp4",
  "original_filename": "my_video.mp4"
}
```

Response:
```json
{
  "job_id": "uuid",
  "task_id": "celery-task-id",
  "status": "processing",
  "message": "Conversion job has been queued"
}
```

### Check Job Status
```bash
GET /api/v1/videos/jobs/{job_id}
```

Response:
```json
{
  "job_id": "uuid",
  "status": "completed",
  "original_filename": "my_video.mp4",
  "master_playlist_url": "https://bucket.s3.amazonaws.com/hls/uuid/master.m3u8"
}
```

### Get Stream URL
```bash
GET /api/v1/videos/stream/{job_id}
```

Response:
```json
{
  "job_id": "uuid",
  "stream_url": "https://bucket.s3.amazonaws.com/hls/uuid/master.m3u8",
  "status": "completed"
}
```

### List Jobs
```bash
GET /api/v1/videos/jobs?page=1&page_size=20&status_filter=completed
```

### Delete Job
```bash
DELETE /api/v1/videos/jobs/{job_id}?delete_s3_files=true
```

## Frontend Integration

Use any HLS player library to play the stream:

### Using hls.js
```javascript
import Hls from 'hls.js';

const video = document.getElementById('video');
const streamUrl = 'https://bucket.s3.amazonaws.com/hls/uuid/master.m3u8';

if (Hls.isSupported()) {
  const hls = new Hls();
  hls.loadSource(streamUrl);
  hls.attachMedia(video);
} else if (video.canPlayType('application/vnd.apple.mpegurl')) {
  // Native HLS support (Safari)
  video.src = streamUrl;
}
```

### Using Video.js
```html
<video-js id="video" class="vjs-default-skin" controls>
  <source src="https://bucket.s3.amazonaws.com/hls/uuid/master.m3u8" type="application/x-mpegURL">
</video-js>
```

## Configuration

See `.env.example` for all configuration options:

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_ACCESS_KEY_ID` | AWS access key | - |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | - |
| `AWS_REGION` | AWS region | us-east-1 |
| `S3_BUCKET_NAME` | S3 bucket name | - |
| `S3_ENDPOINT_URL` | Custom S3 endpoint (MinIO) | - |
| `DATABASE_URL` | PostgreSQL connection URL | - |
| `REDIS_URL` | Redis connection URL | - |

## HLS Profiles

Default encoding profiles:

| Profile | Resolution | Video Bitrate | Audio Bitrate |
|---------|------------|---------------|---------------|
| 360p | 640x360 | 800 kbps | 96 kbps |
| 480p | 854x480 | 1.4 Mbps | 128 kbps |
| 720p | 1280x720 | 2.8 Mbps | 128 kbps |
| 1080p | 1920x1080 | 5 Mbps | 192 kbps |

Only profiles that match or are below the source resolution will be generated.

## S3 Bucket Policy

For public HLS streaming, configure your S3 bucket policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadHLS",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::your-bucket/hls/*"
    }
  ]
}
```

## License

MIT

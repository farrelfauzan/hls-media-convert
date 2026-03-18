// ── Request types ──

export interface UploadUrlRequest {
  /** Name of the file to upload */
  filename: string;
  /** MIME type of the file (e.g. "video/mp4") */
  content_type: string;
}

export interface ConvertRequest {
  /** S3 key of the uploaded video */
  s3_key: string;
  /** Original filename */
  original_filename: string;
  /** Webhook URL to receive a POST when conversion completes or fails */
  callback_url?: string;
}

export interface ListJobsParams {
  /** Page number (default: 1) */
  page?: number;
  /** Items per page (default: 20, max: 100) */
  page_size?: number;
  /** Filter by status: pending | processing | completed | failed */
  status?: JobStatus;
}

// ── Response types ──

export type JobStatus = "pending" | "processing" | "completed" | "failed";

export interface PresignedUploadResponse {
  /** URL to upload the file */
  upload_url: string;
  /** Form fields to include in upload */
  fields: Record<string, string>;
  /** S3 key where file will be stored */
  s3_key: string;
  /** URL expiration in seconds */
  expires_in: number;
}

export interface ConversionStartResponse {
  /** Unique job identifier */
  job_id: string;
  /** Celery task identifier */
  task_id: string;
  /** Initial status */
  status: string;
  /** Status message */
  message: string;
}

export interface JobResponse {
  /** Unique job identifier */
  job_id: string;
  /** Current job status */
  status: JobStatus;
  /** Original filename */
  original_filename: string;
  /** Source video S3 key */
  source_s3_key: string;
  /** Output HLS S3 prefix */
  output_s3_prefix: string | null;
  /** Master playlist URL */
  master_playlist_url: string | null;
  /** Error message if failed */
  error_message: string | null;
  /** Job creation time */
  created_at: string | null;
  /** Job completion time */
  completed_at: string | null;
}

export interface JobListResponse {
  jobs: JobResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface TaskStatusResponse {
  task_id: string;
  status: string;
  progress: number | null;
  result: Record<string, unknown> | null;
}

export interface HealthResponse {
  status: string;
}

// ── Webhook payload (received at your callback_url) ──

export interface WebhookPayload {
  /** Unique job identifier */
  job_id: string;
  /** Conversion result: "completed" or "failed" */
  status: "completed" | "failed";
  /** Public URL of the HLS master playlist (present when completed) */
  master_playlist_url: string | null;
  /** Error details (present when failed) */
  error_message: string | null;
}

// ── SDK config ──

export interface HlsConverterConfig {
  /** Base URL of the HLS converter API (e.g. "https://hls-api.example.com") */
  baseUrl: string;
  /** API prefix (default: "/api/v1") */
  apiPrefix?: string;
  /** Request timeout in milliseconds (default: 30000) */
  timeout?: number;
  /** Custom headers to include in every request */
  headers?: Record<string, string>;
}

export interface HlsApiError {
  status: number;
  detail: string;
}

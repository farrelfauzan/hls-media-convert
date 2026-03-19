import type {
  HlsConverterConfig,
  HlsApiError,
  UploadUrlRequest,
  PresignedUploadResponse,
  ConvertRequest,
  ConversionStartResponse,
  ListJobsParams,
  JobListResponse,
  JobResponse,
  TaskStatusResponse,
  HealthResponse,
} from "./types";

export class HlsConverterError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "HlsConverterError";
    this.status = status;
    this.detail = detail;
  }
}

export class HlsConverter {
  private readonly baseUrl: string;
  private readonly apiPrefix: string;
  private readonly timeout: number;
  private readonly headers: Record<string, string>;
  private readonly apiKey?: string;

  constructor(config: HlsConverterConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.apiPrefix = config.apiPrefix ?? "/api/v1";
    this.timeout = config.timeout ?? 30_000;
    this.headers = config.headers ?? {};
    this.apiKey = config.apiKey;
  }

  // ── Internal helpers ──

  private url(path: string): string {
    return `${this.baseUrl}${this.apiPrefix}${path}`;
  }

  private async request<T>(
    method: string,
    url: string,
    body?: unknown,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const init: RequestInit = {
        method,
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          ...(this.apiKey ? { "X-API-Key": this.apiKey } : {}),
          ...this.headers,
        },
        signal: controller.signal,
      };

      if (body !== undefined) {
        init.body = JSON.stringify(body);
      }

      const res = await fetch(url, init);

      if (!res.ok) {
        let detail: string;
        try {
          const err: HlsApiError = await res.json();
          detail = err.detail;
        } catch {
          detail = res.statusText;
        }
        throw new HlsConverterError(res.status, detail);
      }

      return (await res.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Public API ──

  /**
   * Generate a presigned URL for uploading a video directly to S3.
   */
  async getUploadUrl(
    params: UploadUrlRequest,
  ): Promise<PresignedUploadResponse> {
    return this.request<PresignedUploadResponse>(
      "POST",
      this.url("/videos/upload-url"),
      params,
    );
  }

  /**
   * Upload a file to S3 using the presigned URL obtained from `getUploadUrl`.
   */
  async uploadFile(
    presigned: PresignedUploadResponse,
    file: Blob | Buffer,
  ): Promise<void> {
    const form = new FormData();

    for (const [key, value] of Object.entries(presigned.fields)) {
      form.append(key, value);
    }
    form.append(
      "file",
      file instanceof Blob ? file : new Blob([file as BlobPart]),
    );

    const res = await fetch(presigned.upload_url, {
      method: "POST",
      body: form,
    });

    if (!res.ok) {
      throw new HlsConverterError(
        res.status,
        `S3 upload failed: ${res.statusText}`,
      );
    }
  }

  /**
   * Start an HLS conversion job.
   *
   * @param params.callback_url - Your webhook endpoint that will receive the result.
   */
  async convert(params: ConvertRequest): Promise<ConversionStartResponse> {
    return this.request<ConversionStartResponse>(
      "POST",
      this.url("/videos/convert"),
      params,
    );
  }

  /**
   * List conversion jobs with optional pagination and status filter.
   */
  async listJobs(params?: ListJobsParams): Promise<JobListResponse> {
    const query = new URLSearchParams();
    if (params?.page) query.set("page", String(params.page));
    if (params?.page_size) query.set("page_size", String(params.page_size));
    if (params?.status) query.set("status", params.status);

    const qs = query.toString();
    return this.request<JobListResponse>(
      "GET",
      this.url(`/videos/jobs${qs ? `?${qs}` : ""}`),
    );
  }

  /**
   * Get details of a specific conversion job.
   */
  async getJob(jobId: string): Promise<JobResponse> {
    return this.request<JobResponse>(
      "GET",
      this.url(`/videos/jobs/${encodeURIComponent(jobId)}`),
    );
  }

  /**
   * Get the real-time Celery task status for a job (includes progress %).
   */
  async getJobTaskStatus(jobId: string): Promise<TaskStatusResponse> {
    return this.request<TaskStatusResponse>(
      "GET",
      this.url(`/videos/jobs/${encodeURIComponent(jobId)}/status`),
    );
  }

  /**
   * Poll a job until it reaches a terminal state (completed / failed).
   *
   * @param jobId       - Job identifier
   * @param intervalMs  - Polling interval in ms (default: 3000)
   * @param maxAttempts - Max poll iterations (default: 200, ~10 min at 3s)
   */
  async waitForCompletion(
    jobId: string,
    intervalMs = 3000,
    maxAttempts = 200,
  ): Promise<JobResponse> {
    for (let i = 0; i < maxAttempts; i++) {
      const job = await this.getJob(jobId);
      if (job.status === "completed" || job.status === "failed") {
        return job;
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new HlsConverterError(408, "Timed out waiting for job completion");
  }

  /**
   * Health check – verify the API is reachable.
   */
  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", this.url("/health"));
  }
}

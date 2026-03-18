# HLS Converter SDK

TypeScript/JavaScript SDK for the HLS Video Converter API.

## Installation

```bash
pnpm add hls-converter-sdk
# or
npm install hls-converter-sdk
# or
yarn add hls-converter-sdk
```

## Quick Start

```typescript
import { HlsConverter } from "hls-converter-sdk";

const client = new HlsConverter({
  baseUrl: "https://your-hls-api.example.com",
});

// 1. Get a presigned upload URL
const presigned = await client.getUploadUrl({
  filename: "video.mp4",
  content_type: "video/mp4",
});

// 2. Upload the file to S3
await client.uploadFile(presigned, fileBuffer);

// 3. Start HLS conversion (with webhook)
const job = await client.convert({
  s3_key: presigned.s3_key,
  original_filename: "video.mp4",
  callback_url: "https://your-app.com/webhooks/hls-conversion",
});

console.log(`Job started: ${job.job_id}`);

// 4a. Poll until done (alternative to webhook)
const result = await client.waitForCompletion(job.job_id);
console.log(`HLS URL: ${result.master_playlist_url}`);

// 4b. Or check status manually
const status = await client.getJobTaskStatus(job.job_id);
console.log(`Progress: ${status.progress}%`);
```

## Webhook

When you provide a `callback_url`, the API will POST to that URL when the conversion finishes:

```typescript
import type { WebhookPayload } from "hls-converter-sdk";

// In your NestJS / Express handler:
app.post("/webhooks/hls-conversion", (req, res) => {
  const payload: WebhookPayload = req.body;

  if (payload.status === "completed") {
    console.log(`HLS ready: ${payload.master_playlist_url}`);
  } else {
    console.error(`Conversion failed: ${payload.error_message}`);
  }

  res.sendStatus(200);
});
```

If `WEBHOOK_SECRET` is configured on the server, verify the `X-Webhook-Signature` header (HMAC-SHA256 hex digest of the sorted JSON body).

## API Reference

### `new HlsConverter(config)`

| Option      | Type                      | Default      | Description                    |
|-------------|---------------------------|--------------|--------------------------------|
| `baseUrl`   | `string`                  | **required** | Base URL of the HLS API        |
| `apiPrefix` | `string`                  | `"/api/v1"`  | API path prefix                |
| `timeout`   | `number`                  | `30000`      | Request timeout in ms          |
| `headers`   | `Record<string, string>`  | `{}`         | Custom headers for all requests|

### Methods

| Method                     | Description                                          |
|----------------------------|------------------------------------------------------|
| `getUploadUrl(params)`     | Get a presigned S3 upload URL                        |
| `uploadFile(presigned, file)` | Upload a file using the presigned URL             |
| `convert(params)`          | Start an HLS conversion job                          |
| `listJobs(params?)`        | List jobs with pagination and optional status filter |
| `getJob(jobId)`            | Get details of a specific job                        |
| `getJobTaskStatus(jobId)`  | Get real-time Celery task status with progress       |
| `waitForCompletion(jobId)` | Poll until the job completes or fails                |
| `health()`                 | Health check                                         |

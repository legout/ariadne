export interface ExactUpload {
  baseUrl: string;
  token: string;
  sourceId: string;
  filename: string;
  retryKey: string;
  bytes: Uint8Array;
}

export interface UploadReceipt {
  upload_id: string;
  source_id: string;
  filename: string;
  sha256: string;
  size: number;
  reused: boolean;
}

export async function uploadExactBytes(input: ExactUpload): Promise<UploadReceipt> {
  const response = await fetch(`${input.baseUrl.replace(/\/$/, "")}/uploads`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${input.token}`,
      "Content-Type": "application/octet-stream",
      "X-Lumio-Source-ID": input.sourceId,
      "X-Lumio-Filename": input.filename,
      "X-Lumio-Retry-Key": input.retryKey,
    },
    body: Uint8Array.from(input.bytes).buffer as ArrayBuffer,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { error?: string };
      detail = body.error ?? detail;
    } catch {
      // Keep the status-only failure when the server has no JSON diagnostic.
    }
    throw new Error(`workspace upload failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as UploadReceipt;
}

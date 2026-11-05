import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import test from "node:test";
import { uploadExactBytes } from "../upload.ts";

const FIXTURE = Buffer.from([
  0xef, 0xbb, 0xbf, 0x23, 0x20, 0x41, 0x0d, 0x0a, 0x42, 0x0d, 0x0a, 0xff,
]);
const EXPECTED_SHA256 = "d95fc992c600e925ae90923a4e087048fbcda2c71eb2ba186afbd1dd46e67289";

test("uploadExactBytes sends the independent original bytes unchanged", async () => {
  assert.equal(createHash("sha256").update(FIXTURE).digest("hex"), EXPECTED_SHA256);
  let received: Buffer | undefined;
  let headers: Record<string, string | string[] | undefined> | undefined;
  const server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      received = Buffer.concat(chunks);
      headers = request.headers;
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          upload_id: "opaque-upload",
          source_id: "runbook-source",
          filename: "runbook.md",
          sha256: EXPECTED_SHA256,
          size: FIXTURE.length,
          reused: false,
        }),
      );
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    assert(address && typeof address === "object");
    const receipt = await uploadExactBytes({
      baseUrl: `http://127.0.0.1:${address.port}`,
      token: "synthetic-not-a-credential",
      sourceId: "runbook-source",
      filename: "runbook.md",
      retryKey: "retry-fixture",
      bytes: FIXTURE,
    });
    assert(received !== undefined);
    assert.deepEqual(received, FIXTURE);
    assert.equal(createHash("sha256").update(received).digest("hex"), EXPECTED_SHA256);
    assert.equal(headers?.["content-type"], "application/octet-stream");
    assert.equal(headers?.["x-lumio-source-id"], "runbook-source");
    assert.equal(headers?.["x-lumio-filename"], "runbook.md");
    assert.equal(headers?.["x-lumio-retry-key"], "retry-fixture");
    assert.equal(receipt.sha256, EXPECTED_SHA256);
  } finally {
    // Do not leave the fixture's keep-alive connection open after the check.
    server.closeAllConnections();
    server.close();
  }
});

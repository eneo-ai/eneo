/**
 * Executes the TypeScript client the Flow integration guide publishes.
 *
 * The guide advertises this listing as copy-pasteable, so the parts that are
 * easy to get subtly wrong — sending the reviewed step's own value rather than
 * its payload, and refusing the checkpoints that cannot take an edit — are
 * exercised here against a stubbed `fetch` rather than merely parsed.
 */
import { test, expect, afterEach } from "bun:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const appDir = dirname(dirname(fileURLToPath(import.meta.url)));
const integratingGuide = join(
  appDir,
  "src",
  "content",
  "guides",
  "flows",
  "integrating-flows.mdx",
);

async function loadPublishedClient() {
  const source = await readFile(integratingGuide, "utf8");
  const blocks = [...source.matchAll(/^```ts\n([\s\S]*?)^```/gm)].map(
    (m) => m[1],
  );
  if (blocks.length !== 1)
    throw new Error(`expected one ts block, found ${blocks.length}`);
  const { outputText } = ts.transpileModule(blocks[0], {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
    },
  });
  const dir = await mkdtemp(join(tmpdir(), "eneo-published-client-"));
  try {
    const file = join(dir, "client.mjs");
    await writeFile(file, outputText, "utf8");
    return await import(pathToFileURL(file).href);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

/** Records the request the client would send and returns a canned checkpoint. */
function stubFetch(recorded) {
  return async (url, init) => {
    recorded.url = url;
    recorded.init = init;
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
}

const editableCheckpoint = {
  id: "cp-1",
  revision: 3,
  review_mode: "edit",
  current_payload_json: {
    text: '{"decisions": "old"}',
    structured: { decisions: "old" },
  },
};

const fileBackedCheckpoint = {
  ...editableCheckpoint,
  current_payload_json: {
    text: "Frozen preview of a long transcript",
    structured: { decisions: "old" },
    text_overflow: { generated_file_ids: ["file-1"] },
  },
};

const viewOnlyCheckpoint = { ...editableCheckpoint, review_mode: "view" };

test("editCheckpoint sends the step's value and nothing else", async () => {
  const { EneoFlows } = await loadPublishedClient();
  const recorded = {};
  globalThis.fetch = stubFetch(recorded);

  const client = new EneoFlows("https://eneo.example.se/api/v1", "sk_test");
  await client.editCheckpoint("flow-1", "run-1", editableCheckpoint, {
    decisions: "new",
  });

  const body = JSON.parse(recorded.init.body);
  expect(body.expected_checkpoint_revision).toBe(3);
  expect(body.edited_value).toEqual({ decisions: "new" });
  // The server owns the payload envelope; resending it is what the old
  // contract required and what this one refuses to do.
  expect(body.current_payload_json).toBeUndefined();
  expect(recorded.url).toBe(
    "https://eneo.example.se/api/v1/flows/flow-1/runs/run-1/review-checkpoints/cp-1/",
  );
  expect(recorded.init.method).toBe("PATCH");
});

test("editCheckpoint refuses a checkpoint opened for viewing", async () => {
  const { EneoFlows } = await loadPublishedClient();
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response("{}", { status: 200 });
  };

  const client = new EneoFlows("https://eneo.example.se/api/v1", "sk_test");
  expect(() =>
    client.editCheckpoint("flow-1", "run-1", viewOnlyCheckpoint, {
      decisions: "new",
    }),
  ).toThrow(/flow_review_edit_not_allowed/);
  expect(called).toBe(false);
});

test("editCheckpoint refuses a file-backed output", async () => {
  const { EneoFlows } = await loadPublishedClient();
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response("{}", { status: 200 });
  };

  const client = new EneoFlows("https://eneo.example.se/api/v1", "sk_test");
  expect(() =>
    client.editCheckpoint("flow-1", "run-1", fileBackedCheckpoint, {
      decisions: "new",
    }),
  ).toThrow(/flow_review_edit_file_backed_unsupported/);
  expect(called).toBe(false);
});

test("the client builds request URLs from the configured API base", async () => {
  const { EneoFlows } = await loadPublishedClient();
  const recorded = {};
  globalThis.fetch = stubFetch(recorded);

  const client = new EneoFlows(
    "https://eneo.example.se/eneo-api/v1",
    "sk_test",
  );
  await client.getRun("flow-1", "run-1");

  expect(recorded.url).toBe(
    "https://eneo.example.se/eneo-api/v1/flows/flow-1/runs/run-1/",
  );
  expect(recorded.init.headers["X-API-Key"]).toBe("sk_test");
});

test("resume sends the required Idempotency-Key header", async () => {
  const { EneoFlows } = await loadPublishedClient();
  const recorded = {};
  globalThis.fetch = stubFetch(recorded);

  const client = new EneoFlows("https://eneo.example.se/api/v1", "sk_test");
  await client.resumeCheckpoint("flow-1", "run-1", "cp-1", 4, "resume-cp-1");

  expect(recorded.init.headers["Idempotency-Key"]).toBe("resume-cp-1");
  expect(recorded.url.endsWith("/review-checkpoints/cp-1/resume/")).toBe(true);
});

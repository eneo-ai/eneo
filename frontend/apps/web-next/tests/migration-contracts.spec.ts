import type { Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { policyDraft } from "../src/features/admin/storage/storage-policy";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import {
  apiPath,
  askChatQuestion,
  conversationLog,
  createSpace,
  E2E_CREDENTIALS,
  isChatStream,
  openCreateCollectionDialog,
  uniqueName
} from "./helpers";

const SLOW_MARKER = "E2E_NATIVE_LONG_STREAM";
const PARTIAL = "Native stream partial";
const FINISHED = "Native stream finished";
const POLICY_PATH = "/api/v1/admin/object-content-policy";
const MIB = 1024 ** 2;

async function readPolicy(page: Page): Promise<Schema<"DeploymentPolicyPublic">> {
  const response = await page.request.get(POLICY_PATH);
  expect(response.ok()).toBe(true);
  return response.json();
}

async function writePolicy(
  page: Page,
  policy: Schema<"DeploymentPolicyUpdate">
): Promise<Schema<"DeploymentPolicyPublic">> {
  const response = await page.evaluate(
    async ({ path, policy }) => {
      const session = await fetch("/api/v1/auth/session/");
      const generation = session.headers.get("Eneo-Session-Generation");
      if (session.status !== 204 || !generation)
        throw new Error("Policy fixture requires a live browser session");
      const response = await fetch(path, {
        method: "PUT",
        headers: { "content-type": "application/json", "Eneo-Session-Generation": generation },
        body: JSON.stringify(policy)
      });
      return { ok: response.ok, body: await response.text() };
    },
    { path: POLICY_PATH, policy }
  );
  expect(response.ok, response.body).toBe(true);
  return JSON.parse(response.body) as Schema<"DeploymentPolicyPublic">;
}

/** An unreferenced stream pads a one-page PDF without adding extracted text. */
function knowledgePdf(size: number): Buffer {
  function build(padding: number) {
    const content = "BT /F1 12 Tf 50 750 Td (Native knowledge upload) Tj ET";
    const objects = [
      "<< /Type /Catalog /Pages 2 0 R >>",
      "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
      "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
      `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
      `<< /Length ${padding} >>\nstream\n${" ".repeat(padding)}\nendstream`
    ];
    let pdf = "%PDF-1.4\n";
    const offsets = [0];
    for (const [index, object] of objects.entries()) {
      offsets.push(Buffer.byteLength(pdf));
      pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
    }
    const xref = Buffer.byteLength(pdf);
    pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
    pdf += offsets
      .slice(1)
      .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
      .join("");
    pdf += `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
    return Buffer.from(pdf);
  }
  const padding = size - build(0).length;
  const candidate = build(padding);
  const result = build(padding + size - candidate.length);
  expect(result.length).toBe(size);
  return result;
}

test(
  "a real provider stream runs longer than 60 seconds and completes in chat",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    test.setTimeout(110_000);
    await page.goto("/spaces/personal/chat");
    const stream = page.waitForResponse(
      (response) => response.request().method() === "POST" && isChatStream(new URL(response.url()))
    );
    const question = uniqueName(`${SLOW_MARKER} complete`);
    const started = performance.now();
    await askChatQuestion(page, question);
    const response = await stream;
    expect(response.status()).toBe(200);
    const log = conversationLog(page);
    await expect(log.getByText(new RegExp(PARTIAL))).toBeVisible({ timeout: 15_000 });
    const firstPartialMs = performance.now() - started;
    await expect(log.getByText(new RegExp(FINISHED))).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Stoppa generering", exact: true })
    ).toBeVisible();
    await expect(log.getByText(new RegExp(FINISHED))).toBeVisible({ timeout: 85_000 });
    await expect(page.getByRole("button", { name: "Stoppa generering", exact: true })).toHaveCount(
      0
    );
    expect(await response.finished()).toBeNull();
    const durationMs = performance.now() - started;
    expect(durationMs).toBeGreaterThan(60_000);
    const sessionId = new URL(page.url()).searchParams.get("session_id");
    expect(sessionId).toBeTruthy();
    const saved = await page.request.get(apiPath(`/conversations/${sessionId}/`));
    expect(saved.ok()).toBe(true);
    const session: Schema<"SessionPublic"> = await saved.json();
    const message = session.messages.find((item) => item.question === question);
    expect(message?.answer).toContain(FINISHED);
    await testInfo.attach("completed-provider-stream.json", {
      body: JSON.stringify(
        {
          session_id: sessionId,
          question_id: message?.id,
          first_partial_ms: firstPartialMs,
          duration_ms: durationMs,
          completed: true
        },
        null,
        2
      ),
      contentType: "application/json"
    });
  }
);

test(
  "Stop persists the visible partial answer from the real slow provider",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    await page.goto("/spaces/personal/chat");
    const question = uniqueName(`${SLOW_MARKER} cancel`);
    await askChatQuestion(page, question);
    const answer = conversationLog(page).getByText(new RegExp(PARTIAL));
    await expect(answer).toBeVisible();
    const visiblePartial = (await answer.innerText()).trim();
    await page.getByRole("button", { name: "Stoppa generering", exact: true }).click();
    await expect(page.getByRole("button", { name: "Stoppa generering", exact: true })).toHaveCount(
      0
    );
    const sessionId = new URL(page.url()).searchParams.get("session_id");
    expect(sessionId).toBeTruthy();
    let persisted: Schema<"Message"> | undefined;
    await expect
      .poll(
        async () => {
          const response = await page.request.get(apiPath(`/conversations/${sessionId}/`));
          expect(response.ok()).toBe(true);
          const session: Schema<"SessionPublic"> = await response.json();
          persisted = session.messages.find((message) => message.question === question);
          return persisted?.answer ?? "";
        },
        { timeout: 15_000 }
      )
      .toContain(visiblePartial);
    expect(persisted?.answer).not.toContain(FINISHED);
    await page.reload();
    await expect(conversationLog(page).getByText(persisted!.answer, { exact: true })).toBeVisible();
    await testInfo.attach("cancelled-provider-stream.json", {
      body: JSON.stringify(
        {
          session_id: sessionId,
          question_id: persisted!.id,
          visible_partial: visiblePartial,
          persisted_partial: persisted!.answer
        },
        null,
        2
      ),
      contentType: "application/json"
    });
  }
);

test(
  "uploads 25 MiB of knowledge and downloads the same original bytes",
  { tag: ["@vite", "@upload-worker"] },
  async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await page.goto("/spaces/personal/chat");
    const originalPolicy = policyDraft(await readPolicy(page));
    try {
      const raised = await writePolicy(page, {
        ...originalPolicy,
        knowledge_file_limit_bytes: 32 * MIB
      });
      const projection = raised.limits.find((limit) => limit.use_case === "knowledge_file");
      expect(projection).toMatchObject({
        effective_bytes: 32 * MIB,
        storage_capacity_bytes: 32 * MIB,
        storage_target: "postgres_inline"
      } satisfies Partial<Schema<"UploadLimitProjection">>);
      const space = await createSpace(page, uniqueName("E2E Native original"));
      await page.goto(`${space}/knowledge`);
      const create = await openCreateCollectionDialog(page);
      await create.getByLabel(/^(namn|name)$/i).fill("Native original");
      await create.getByRole("button", { name: /skapa samling|create collection/i }).click();
      await page.waitForURL(/\/knowledge\/collections\/[^/]+$/);
      // The app context must read the policy projection from this test instance.
      const limitsResponse = page.waitForResponse(
        (response) => new URL(response.url()).pathname === "/api/v1/limits/"
      );
      await page.reload();
      const limits: Schema<"Limits"> = await (await limitsResponse).json();
      expect(
        limits.info_blobs.formats.find((format) => format.mimetype === "application/pdf")?.size
      ).toBe(32 * MIB);
      const bytes = knowledgePdf(25 * MIB);
      const sha256 = createHash("sha256").update(bytes).digest("hex");
      const filename = "native-25-mib.pdf";
      await page.getByRole("button", { name: /ladda upp filer|upload files/i }).click();
      const upload = page.getByRole("dialog", { name: /ladda upp filer|upload files/i });
      await upload
        .locator('input[type="file"]')
        .setInputFiles({ name: filename, mimeType: "application/pdf", buffer: bytes });
      const queued = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          /\/groups\/[^/]+\/info-blobs\/upload\/$/.test(new URL(response.url()).pathname)
      );
      const uploadStarted = performance.now();
      await upload.getByRole("button", { name: /ladda upp filer|upload files/i }).click();
      expect((await queued).status()).toBe(202);
      await expect(upload).toBeHidden();
      await page.getByRole("button", { name: filename, exact: true }).click({ timeout: 60_000 });
      const ingestMs = performance.now() - uploadStarted;
      const preview = page.getByRole("dialog", { name: filename });
      await expect(preview).toContainText("Native knowledge upload");
      const original = preview.getByRole("button", {
        name: /ladda ner original|download original/i
      });
      await expect(original).toBeEnabled();
      const downloading = page.waitForEvent("download");
      await original.click();
      const download = await downloading;
      expect(await download.failure()).toBeNull();
      expect(download.suggestedFilename()).toBe(filename);
      const received = await readFile((await download.path())!);
      expect(received.length).toBe(bytes.length);
      expect(createHash("sha256").update(received).digest("hex")).toBe(sha256);
      await testInfo.attach("knowledge-original.json", {
        body: JSON.stringify(
          { bytes: bytes.length, sha256, ingest_ms: ingestMs, projection },
          null,
          2
        ),
        contentType: "application/json"
      });
    } finally {
      const current = await readPolicy(page);
      const restored = await writePolicy(page, {
        ...originalPolicy,
        expected_revision: current.policy.revision
      });
      expect(policyDraft(restored)).toEqual({
        ...originalPolicy,
        expected_revision: restored.policy.revision
      });
      await testInfo.attach("restored-knowledge-policy.json", {
        body: JSON.stringify(
          {
            restore_expected_revision: current.policy.revision,
            restored_revision: restored.policy.revision,
            knowledge_file_limit_bytes: restored.policy.knowledge_file_limit_bytes
          },
          null,
          2
        ),
        contentType: "application/json"
      });
    }
  }
);

test(
  "an expired browser session redirects once and real login resumes chat",
  { tag: "@vite" },
  async ({ page, context }, testInfo) => {
    const resume = "/spaces/personal/chat";
    await page.goto(resume);
    await expect(page.getByRole("textbox", { name: /^(Fråga|Ask) / })).toBeVisible();
    const cookies = await context.cookies();
    const sessions = cookies.filter((cookie) => /^(eneo_web|__Host-eneo_web)$/.test(cookie.name));
    expect(sessions.length).toBeGreaterThan(0);
    await context.clearCookies({ name: /^(eneo_web|__Host-eneo_web)$/ });
    const redirects: string[] = [];
    page.on("request", (request) => {
      if (
        request.isNavigationRequest() &&
        request.frame() === page.mainFrame() &&
        new URL(request.url()).pathname === "/login"
      )
        redirects.push(request.url());
    });
    await askChatQuestion(page, "Trigger session expiry");
    await page.waitForURL((url) => url.pathname === "/login");
    expect(new URL(page.url()).searchParams.get("next")).toBe(resume);
    expect(redirects).toHaveLength(1);
    await page.locator('input[name="email"]').fill(E2E_CREDENTIALS.username);
    await page.locator('input[name="password"]').fill(E2E_CREDENTIALS.password);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL((url) => url.pathname === resume);
    await expect(page.getByRole("textbox", { name: /^(Fråga|Ask) / })).toBeVisible();
    expect(redirects).toHaveLength(1);
    await testInfo.attach("expired-session-resume.json", {
      body: JSON.stringify({ login_documents: redirects.length, next: resume, resumed: true }),
      contentType: "application/json"
    });
  }
);

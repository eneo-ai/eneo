import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPost, createSpace, sessionResponseHeaders, uniqueName } from "./helpers";

declare global {
  interface Window {
    __appResultPrint?: {
      text: string;
      visibleDocument: boolean;
      shellHidden: boolean;
      controlsHidden: boolean;
      background: string;
    };
  }
}

/** A valid 100 ms PCM WAV whose exact uploaded bytes can be checked on download. */
function audioBytes() {
  const wave = Buffer.alloc(44 + 1600);
  wave.write("RIFF", 0);
  wave.writeUInt32LE(wave.length - 8, 4);
  wave.write("WAVEfmt ", 8);
  wave.writeUInt32LE(16, 16);
  wave.writeUInt16LE(1, 20);
  wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(8000, 24);
  wave.writeUInt32LE(16000, 28);
  wave.writeUInt16LE(2, 32);
  wave.writeUInt16LE(16, 34);
  wave.write("data", 36);
  wave.writeUInt32LE(1600, 40);
  return wave;
}

async function uploadAudio(page: Page, name: string, bytes: Buffer): Promise<Schema<"FilePublic">> {
  return page.evaluate(
    async ({ name, bytes }) => {
      const session = await fetch("/api/v1/auth/session/");
      const generation = session.headers.get("Eneo-Session-Generation");
      if (session.status !== 204 || !generation) throw new Error("Audio upload needs a session");
      const form = new FormData();
      form.set("upload_file", new File([new Uint8Array(bytes)], name, { type: "audio/wav" }));
      const response = await fetch("/api/v1/files/", {
        method: "POST",
        headers: { "Eneo-Session-Generation": generation },
        body: form
      });
      if (!response.ok) throw new Error(`Audio upload failed (${response.status})`);
      return response.json();
    },
    { name, bytes: [...bytes] }
  );
}

async function completedResult(page: Page, routeKind: "space" | "dashboard") {
  const space = await createSpace(page, uniqueName("Result actions"));
  const appId = await apiPost(page, `/spaces/${space.split("/").pop()}/applications/apps/`, {
    name: uniqueName("Result document")
  });
  const runId = await apiPost(page, `/apps/${appId}/runs/`, {
    text: "Input must not print",
    files: []
  });
  const bytes = audioBytes();
  const first = await uploadAudio(page, "intervju.wav", bytes);
  const second = await uploadAudio(page, "annan.wav", bytes);
  const response = await page.request.get(`/api/v1/app-runs/${runId}/`);
  expect(response.status()).toBe(200);
  const pending: Schema<"AppRunPublic"> = await response.json();
  const completed: Schema<"AppRunPublic"> = {
    ...pending,
    status: "complete",
    finished_at: new Date().toISOString(),
    output: "# UTDATA_ONLY\n\nVald **utdata**.\n\n```txt\nprint-output\n```",
    input: {
      text: "Input must not print",
      files: [
        { ...first, transcription: "TRANSKRIPTION_ONE" },
        { ...second, transcription: "TRANSKRIPTION_TWO" }
      ]
    }
  };
  // The workerless stack cannot complete a transcription run. Only its completed
  // run data is a fixture; upload, signing, original download and cookie auth are real.
  await page.route(`**/api/v1/app-runs/${runId}/`, (route) =>
    route.fulfill({
      json: completed,
      headers: sessionResponseHeaders(route)
    })
  );
  await page.addInitScript(() => {
    // A headless browser cannot accept or cancel the platform's print dialog.
    // Inspect the actual print-media layout at the window.print boundary.
    window.print = () => {
      const document = window.document.querySelector<HTMLElement>(
        "body > [data-app-result-print-document]"
      );
      if (!document) throw new Error("Missing selected print document");
      window.__appResultPrint = {
        text: document.innerText,
        visibleDocument: getComputedStyle(document).display === "block",
        shellHidden: [...window.document.body.children]
          .filter((element) => element !== document)
          .every((element) => getComputedStyle(element).display === "none"),
        controlsHidden: [...document.querySelectorAll("button, audio")].every(
          (element) => getComputedStyle(element).display === "none"
        ),
        background: getComputedStyle(window.document.body).backgroundColor
      };
    };
  });
  return {
    path:
      routeKind === "space"
        ? `${space}/apps/${appId}/results/${runId}`
        : `/dashboard/app/${appId}/results/${runId}`,
    bytes,
    file: first,
    output: completed.output!
  };
}

test.use({ hasTouch: true });

for (const routeKind of ["space", "dashboard"] as const) {
  test(`${routeKind} result prints the selected document and downloads exact original audio`, async ({
    page,
    context
  }, testInfo) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const result = await completedResult(page, routeKind);
    await page.goto(result.path);
    const dock = page.getByRole("group", { name: "Resultat, åtgärder", exact: true });
    await expect(page.getByRole("heading", { name: "UTDATA_ONLY", exact: true })).toBeVisible();
    await page.emulateMedia({ media: "print", colorScheme: "dark" });
    await dock
      .getByRole("button", { name: "Skriv ut / Spara utdata som PDF", exact: true })
      .click();
    const outputPrint = await page.evaluate(() => window.__appResultPrint);
    expect(outputPrint).toMatchObject({
      visibleDocument: true,
      shellHidden: true,
      controlsHidden: true,
      background: "rgb(255, 255, 255)"
    });
    expect(outputPrint?.text).toContain("UTDATA_ONLY");
    expect(outputPrint?.text).not.toContain("Input must not print");
    expect(outputPrint?.text).not.toContain("TRANSKRIPTION");
    await expect(page.locator("[data-app-result-print-document]")).toHaveCount(0);
    expect(await page.locator("body").getAttribute("data-app-result-printing")).toBeNull();
    await expect(dock).toBeVisible();
    await page.emulateMedia({ media: null });
    const outputDownload = page.waitForEvent("download");
    await dock.getByRole("button", { name: "Ladda ner", exact: true }).click();
    const output = await outputDownload;
    expect(await readFile((await output.path())!, "utf8")).toBe(result.output);

    await page.setViewportSize({ width: 320, height: 900 });
    await dock.screenshot({ path: testInfo.outputPath("output-actions-320-dark.png") });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      320
    );
    expect(
      (await dock
        .getByRole("button", { name: "Skriv ut / Spara utdata som PDF", exact: true })
        .boundingBox())!.height
    ).toBeGreaterThanOrEqual(44);
    await page.getByRole("tab", { name: "Transkription", exact: true }).click();
    const first = page.getByRole("region", { name: "intervju.wav", exact: true });
    const second = page.getByRole("region", { name: "annan.wav", exact: true });
    await expect(first.locator("audio")).toHaveAttribute(
      "src",
      /\/api\/v1\/files\/.*\/download\/\?token=/
    );
    await second.getByRole("button", { name: "Kopiera transkription", exact: true }).click();
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe("TRANSKRIPTION_TWO");
    await page.emulateMedia({ media: "print" });
    await second
      .getByRole("button", { name: "Skriv ut / Spara transkription som PDF", exact: true })
      .click();
    const transcriptionPrint = await page.evaluate(() => window.__appResultPrint);
    expect(transcriptionPrint).toMatchObject({
      text: "TRANSKRIPTION_TWO",
      visibleDocument: true,
      shellHidden: true,
      controlsHidden: true
    });
    await expect(page.locator("[data-app-result-print-document]")).toHaveCount(0);
    await page.emulateMedia({ media: null });
    const transcriptionDownload = page.waitForEvent("download");
    await second
      .getByRole("button", { name: "Ladda ner transkription som råtext", exact: true })
      .click();
    const transcription = await transcriptionDownload;
    expect(transcription.suggestedFilename()).toBe(output.suggestedFilename());
    expect(await readFile((await transcription.path())!, "utf8")).toBe("TRANSKRIPTION_TWO");

    const signedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/v1/files/${result.file.id}/original/signed-url/`
    );
    const audioDownload = page.waitForEvent("download");
    await first
      .getByRole("button", { name: 'Ladda ner original "intervju.wav"', exact: true })
      .click();
    const signed = await signedResponse;
    expect(signed.status()).toBe(200);
    expect(signed.request().postDataJSON()).toEqual({
      expires_in: 3600,
      content_disposition: "attachment"
    });
    const audio = await audioDownload;
    expect(audio.suggestedFilename()).toBe("intervju.wav");
    expect(new URL(audio.url()).origin).toBe(new URL(page.url()).origin);
    expect(new URL(audio.url()).pathname).toBe(
      `/api/v1/files/${result.file.id}/original/download/`
    );
    expect(
      createHash("sha256")
        .update(await readFile((await audio.path())!))
        .digest("hex")
    ).toBe(createHash("sha256").update(result.bytes).digest("hex"));

    await page.setViewportSize({ width: 320, height: 900 });
    await page.emulateMedia({ colorScheme: "dark" });
    await first.scrollIntoViewIfNeeded();
    await first.screenshot({ path: testInfo.outputPath("transcription-320-dark.png") });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      320
    );
  });
}

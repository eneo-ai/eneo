import { expect, test } from "./csp";
import { audioFlow, silenceWav } from "./flows-fixture";
import type { Schema } from "../src/lib/api/models";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");

test(
  "uploads more than 20 MiB, follows the run and seeks signed audio",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(150_000);
    const flow = await audioFlow(page);
    const statuses: string[] = [];
    page.on("response", async (response) => {
      if (
        response.url().includes(`/flows/${flow.flowId}/runs/`) &&
        response.url().endsWith("/status/") &&
        response.ok()
      ) {
        statuses.push(((await response.json()) as Schema<"FlowRunSummaryPublic">).status);
      }
    });
    await page.goto(flow.url);
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const wav = silenceWav(21 * 1024 * 1024 + 44);
    const uploaded = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/steps/${flow.stepId}/runtime-files/`) &&
        response.request().method() === "POST"
    );
    // Chromium can evict the inspector body for this large POST. Observe the
    // real XHR response in the page without intercepting or replacing transport.
    const uploadedSize = page.evaluate(
      (path) =>
        new Promise<number>((resolve) => {
          const send = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.send = function (body) {
            this.addEventListener("load", () => {
              if (new URL(this.responseURL).pathname !== path) return;
              XMLHttpRequest.prototype.send = send;
              resolve((JSON.parse(this.responseText) as { size: number }).size);
            });
            send.call(this, body);
          };
        }),
      `/api/v1/flows/${flow.flowId}/steps/${flow.stepId}/runtime-files/`
    );
    await dialog
      .locator('input[type="file"]')
      .setInputFiles({ name: "large.wav", mimeType: "audio/wav", buffer: wav });
    const response = await uploaded;
    expect(response.status()).toBe(201);
    expect(await uploadedSize).toBe(wav.length);
    expect(new URL(response.url()).origin).toBe(new URL(page.url()).origin);
    await dialog.getByRole("button", { name: "Granska", exact: true }).click();
    await dialog.getByRole("button", { name: "Starta körningen", exact: true }).click();
    await expect(page).toHaveURL(/\/runs\/[^/?]+$/);
    await expect.poll(() => statuses.includes("completed"), { timeout: 90_000 }).toBe(true);
    expect(statuses.length).toBeGreaterThan(1);
    await page.getByRole("button", { name: "Spela upp ljudet", exact: true }).first().click();
    const audio = page.locator("audio").first();
    await expect(audio).toHaveAttribute("src", /token=/);
    const signedUrl = new URL((await audio.getAttribute("src")) ?? "", page.url());
    const ranged = await page.request.get(signedUrl.toString(), {
      headers: { Range: "bytes=0-43" }
    });
    expect(ranged.status()).toBe(206);
    expect(ranged.headers()["content-range"]).toBe(`bytes 0-43/${wav.length}`);
    expect(ranged.headers()["content-encoding"]).toBeUndefined();
    expect(await ranged.body()).toEqual(wav.subarray(0, 44));
    const outside = await page.request.get(signedUrl.toString(), {
      headers: { Range: `bytes=${wav.length}-` }
    });
    expect(outside.status()).toBe(416);
    expect(outside.headers()["content-range"]).toBe(`bytes */${wav.length}`);
    const unsigned = new URL(signedUrl);
    unsigned.searchParams.delete("token");
    const missing = await page.request.get(unsigned.toString(), {
      headers: { Range: "bytes=0-43" }
    });
    expect(missing.status()).toBe(422); // The signed endpoint requires the token query parameter.
    unsigned.searchParams.set("token", "invalid");
    const invalid = await page.request.get(unsigned.toString(), {
      headers: { Range: "bytes=0-43" }
    });
    expect([401, 403]).toContain(invalid.status());
    await expect
      .poll(() => audio.evaluate((element: HTMLAudioElement) => element.readyState))
      .toBeGreaterThanOrEqual(1);
    await audio.evaluate((element: HTMLAudioElement) => {
      element.currentTime = 7;
    });
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => !element.seeking && element.currentTime >= 7)
      )
      .toBe(true);
  }
);

import { expect, test } from "./csp";
import { audioFlow } from "./flows-fixture";

test.skip(!process.env.E2E_BASE_URL, "Verifies Flows on FastAPI serving the Vite build.");
test.use({
  permissions: ["microphone"],
  launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] }
});

test(
  "records through the built worklet and ticket-protected live socket",
  { tag: "@vite" },
  async ({ page }) => {
    test.setTimeout(90_000);
    const flow = await audioFlow(page, true);
    await page.goto(flow.url);
    await page.getByRole("button", { name: "Kör flödet", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("checkbox", { name: "Visa text medan du spelar in", exact: true })
    ).toBeChecked();
    // AudioWorklet fetches are not exposed as page response events. Check the
    // served asset here; the live transcript below proves the browser loaded it.
    const workletResponse = await page.request.get("/flows/pcm16-worklet.js");
    expect(workletResponse.status()).toBe(200);
    expect(workletResponse.headers()["content-type"]).toMatch(/javascript/);
    expect(workletResponse.headers()["x-content-type-options"]).toBe("nosniff");
    expect(workletResponse.headers()["cache-control"]).toBe("no-cache");
    await dialog.getByRole("button", { name: "Spela in", exact: true }).click();
    await expect(
      dialog.getByText("E2E live transcription: mikrofonen fungerar.", { exact: true })
    ).toBeVisible({ timeout: 20_000 });
    await page.screenshot({
      path: test.info().outputPath("flow-live-recording-desktop.png"),
      fullPage: true
    });
    await dialog.getByRole("button", { name: "Stoppa", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Stoppa", exact: true })).toBeHidden();
    const refusal = await page.evaluate(
      () =>
        new Promise<{ opened: boolean; code: number | null }>((resolve) => {
          const socket = new WebSocket(
            `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v1/live-transcription`,
            ["eneo-live.v1", "ticket.invalid"]
          );
          socket.onopen = () => {
            socket.close();
            resolve({ opened: true, code: null });
          };
          socket.onclose = (event) => resolve({ opened: false, code: event.code });
        })
    );
    expect(refusal.opened).toBe(false);
    expect(refusal.code).toBe(1006); // HTTP 403 refuses the handshake before a WebSocket close frame exists.
    const missing = await page.request.get("/flows/missing-worklet.js");
    expect(missing.status()).toBe(404);
    expect(missing.headers()["content-type"]).not.toMatch(/text\/html/);
    const contentUrl = new URL("/flows/pcm16-worklet.js", page.url());
    contentUrl.hostname = "127.0.0.1";
    const isolated = await page.request.get(contentUrl.toString());
    expect(isolated.status()).toBe(404);
    expect(isolated.headers()["content-type"]).not.toMatch(/javascript|text\/html/);
  }
);

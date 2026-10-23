// Run after tool-runtime's build:views. Exercises the shipped chart in a bounded
// iframe with the production host bridge, without an application server or model.
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "playwright";

const web = fileURLToPath(new URL("..", import.meta.url));
let browser, chartHtml, hostScript;
before(async () => {
  chartHtml = await readFile(
    new URL("../../../../tool-runtime/dist/views/chart.html", import.meta.url),
    "utf8"
  );
  hostScript = (
    await build({
      stdin: {
        contents: `
        import { McpAppBridge } from './src/lib/features/chat/mcp-apps/bridge.ts';
        window.bridge = new McpAppBridge({
          iframe: document.querySelector('iframe'), html: '', displayMode: 'fullscreen',
          hostContext: () => ({ locale: 'en', theme: 'light' }),
          getToolResult: async () => ({ structuredContent: window.toolResult ?? {
            presentation: 'interactive', chart: {
              type: 'line', title: 'Budget development by department',
              labels: ['January', 'February', 'March', 'April'],
              series: Array.from({length: 6}, (_, i) => ({ name: 'Department ' + i, values: [1, 2, 3, 4] }))
            }
          } })
        });
        window.bridge.update({ input: {}, resultReady: true });
      `,
        resolveDir: web,
        loader: "ts"
      },
      bundle: true,
      write: false,
      platform: "browser",
      format: "iife"
    })
  ).outputFiles[0].text;
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
});

for (const height of [320, 450]) {
  test(`expanded chart scrolls to its table in a ${height}px panel`, async () => {
    const page = await browser.newPage({ viewport: { width: 800, height: 800 } });
    page.setDefaultTimeout(5000);
    try {
      await page.setContent(
        `<iframe title="Chart" style="width:420px;height:${height}px;border:0"></iframe>`
      );
      await page.addScriptTag({ content: hostScript });
      await page.locator("iframe").evaluate((frame, html) => {
        frame.srcdoc = html;
      }, chartHtml);
      const app = page.frameLocator("iframe");
      await app.locator(".eneo-plot svg").waitFor();
      await app.getByRole("button", { name: "Table", exact: true }).click();
      const view = app.locator(".eneo-view");
      await view.evaluate((element) => {
        element.scrollTop = 0;
      });
      const plot = await app.locator(".eneo-plot").boundingBox();
      assert.ok(plot.height >= 420, "The plot must retain its readable height with the table open");
      await page.mouse.move(plot.x + plot.width / 2, Math.min(plot.y + 50, height - 10));
      await page.mouse.wheel(0, 450);
      await page.waitForFunction(
        () =>
          document.querySelector("iframe").contentDocument.querySelector(".eneo-view").scrollTop > 0
      );
      const rows = app.getByRole("region", { name: "Rows" });
      const bounds = await rows.boundingBox();
      assert.ok(bounds.height > 0, "The table must not shrink to zero height");
      assert.ok(
        bounds.y < height && bounds.y + bounds.height > 0,
        "Table is reachable inside the viewport"
      );
      assert.equal(
        await app.getByRole("button", { name: "Reset zoom" }).isDisabled(),
        true,
        "Scrolling does not zoom the chart"
      );
    } finally {
      await page.close();
    }
  });
}

test("a table keeps a readable rows area in a short panel", async () => {
  const tableHtml = await readFile(
    new URL("../../../../tool-runtime/dist/views/query-result.html", import.meta.url),
    "utf8"
  );
  const page = await browser.newPage({ viewport: { width: 800, height: 800 } });
  page.setDefaultTimeout(5000);
  try {
    await page.setContent(
      '<iframe title="Table" style="width:420px;height:320px;border:0"></iframe>'
    );
    await page.evaluate(() => {
      window.toolResult = {
        columns: ["Department", "Cost"],
        rows: Array.from({ length: 100 }, (_, i) => [`Department ${i + 1}`, i]),
        truncated: false
      };
    });
    await page.addScriptTag({ content: hostScript });
    await page.locator("iframe").evaluate((frame, html) => {
      frame.srcdoc = html;
    }, tableHtml);
    const app = page.frameLocator("iframe");
    const rows = app.getByRole("region", { name: "Rows" });
    await rows.waitFor();
    const dimensions = await rows.evaluate((element) => ({
      height: element.clientHeight,
      scroll: element.scrollHeight
    }));
    assert.ok(dimensions.height >= 320, "Rows must keep useful room even when controls need space");
    assert.ok(dimensions.scroll > dimensions.height, "Long results remain scrollable");
    await rows.press("Control+End");
    await page.waitForFunction(
      () =>
        document.querySelector("iframe").contentDocument.querySelector(".eneo-rows").scrollTop > 0
    );
  } finally {
    await page.close();
  }
});

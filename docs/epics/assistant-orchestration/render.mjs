import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const directory = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 820, height: 1000 },
    deviceScaleFactor: 2,
  });
  for (const name of ["overview", "flow", "chat", "proof"]) {
    await page.goto(pathToFileURL(path.join(directory, `${name}.html`)).href);
    await page.evaluate(() => document.fonts.ready);
    const overflow = await page.evaluate(() =>
      [...document.querySelectorAll(".page, .box, .layer > div, .window, .proof-row > div")]
        .filter((element) => element.scrollWidth > element.clientWidth + 1)
        .map((element) => element.textContent.trim().slice(0, 90))
    );
    if (overflow.length) throw new Error(`${name}: overflow in ${overflow.join("; ")}`);
    await page.locator(".page").screenshot({
      path: path.join(directory, `orchestration-${name}.png`),
    });
    console.log(`Rendered orchestration-${name}.png`);
  }
} finally {
  await browser.close();
}

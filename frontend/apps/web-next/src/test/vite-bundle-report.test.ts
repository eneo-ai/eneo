import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { build } from "vite";
import { expect, it } from "vitest";
import { bundleReport, type BundleReport } from "../../scripts/vite-bundle-report";

it("reports rendered modules through boot's dynamic import and each static closure", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "eneo-bundle-report-"));
  try {
    const files = {
      "package.json": '{"type":"module"}',
      "index.html": '<script type="module" src="/src/main.ts"></script>',
      "src/main.ts": 'void import("./render-app").then(({render}) => render());',
      "src/render-app.tsx": `import {diagram} from "mermaid";
        export function render() { document.body.dataset.diagram = diagram; }
        document.body.onclick = () => import("./features/chat/chat-page").then(m => m.chat());`,
      "src/features/chat/chat-page.tsx": `export function chat() {
        document.body.onclick = () => import("driver.js").then(m => m.driver());
      }`,
      "node_modules/mermaid/package.json": '{"type":"module","exports":"./index.js"}',
      "node_modules/mermaid/index.js": 'export const diagram = "diagram";',
      "node_modules/driver.js/package.json": '{"type":"module","exports":"./index.js"}',
      "node_modules/driver.js/index.js":
        'export function driver() { document.body.dataset.tour = "started"; }'
    };
    for (const [file, source] of Object.entries(files)) {
      await mkdir(path.dirname(path.join(root, file)), { recursive: true });
      await writeFile(path.join(root, file), source);
    }
    await build({
      configFile: false,
      root,
      plugins: [bundleReport()],
      logLevel: "silent",
      build: {
        minify: false,
        rolldownOptions: {
          output: {
            entryFileNames: "assets/start.js",
            chunkFileNames: "assets/[hash].js",
            codeSplitting: { groups: [{ name: "shared", test: /node_modules\/mermaid\// }] }
          }
        }
      }
    });
    const report: BundleReport = JSON.parse(
      await readFile(path.join(root, "node_modules/.cache/vite-bundle-report.json"), "utf8")
    );
    expect(report.scopes.startup.modules).toContain("node_modules/mermaid/index.js");
    expect(report.scopes.startup.modules).not.toContain("node_modules/driver.js/index.js");
    expect(report.scopes.chat?.modules).not.toContain("node_modules/driver.js/index.js");
    expect(report.chunks.some((chunk) => "node_modules/driver.js/index.js" in chunk.modules)).toBe(
      true
    );
    expect(report.scopes.chat?.modules).not.toContain("node_modules/mermaid/index.js");
    const shared = report.chunks.find((chunk) => "node_modules/mermaid/index.js" in chunk.modules)!;
    const roots = report.chunks.filter((chunk) =>
      report.scopes.startup.roots.includes(chunk.fileName)
    );
    expect(report.scopes.startup.roots).not.toContain(shared.fileName);
    expect(roots.some((chunk) => chunk.imports.includes(shared.fileName))).toBe(true);
    expect(report.scopes.startup.chunks).toContain(shared.fileName);
    expect(report.scopes.startup.bytes).toBeGreaterThanOrEqual(
      roots.reduce((bytes, chunk) => bytes + chunk.bytes, 0) + shared.bytes
    );
    expect(report.chunks.every((chunk) => !/mermaid|driver|chat/.test(chunk.fileName))).toBe(true);
    expect(JSON.stringify(report)).not.toContain(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it("reports an absent chat route and removes stale evidence when a rebuild fails", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "eneo-bundle-failure-"));
  const reportPath = path.join(root, "node_modules/.cache/vite-bundle-report.json");
  const options = {
    configFile: false as const,
    root,
    plugins: [bundleReport()],
    logLevel: "silent" as const
  };
  try {
    await writeFile(
      path.join(root, "index.html"),
      '<script type="module" src="/main.js"></script>'
    );
    await writeFile(path.join(root, "main.js"), 'document.body.textContent = "Ready";');
    await build(options);
    const report: BundleReport = JSON.parse(await readFile(reportPath, "utf8"));
    expect(report.scopes.chat).toBeNull();
    expect(report.scopes.startup.bytes).toBeGreaterThan(0);

    await writeFile(path.join(root, "main.js"), 'import "./missing-module.js";');
    await expect(build(options)).rejects.toThrow(/missing-module/);
    await expect(readFile(reportPath, "utf8")).rejects.toMatchObject({ code: "ENOENT" });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it.each([
  ["startup", "node_modules/driver.js/index.js"],
  ["chat", "node_modules/driver.js/index.js"],
  ["chat", "node_modules/@tiptap/core/index.js"],
  ["chat", "node_modules/prosemirror-view/index.js"],
  ["chat", "src/components/ai-elements/answer-clipboard.ts"]
])("rejects an eager %s dependency on %s", async (scope, dependency) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "eneo-bundle-boundary-"));
  try {
    const owner = scope === "startup" ? "src/render-app.tsx" : "src/features/chat/chat-page.tsx";
    const files = {
      "package.json": '{"type":"module"}',
      "index.html": '<script type="module" src="/src/render-app.tsx"></script>',
      "src/render-app.tsx": 'document.body.onclick = () => import("./features/chat/chat-page");',
      [owner]: `import {start} from "/${dependency}"; start();`,
      [dependency]: 'export function start() { document.body.dataset.loaded = "yes"; }'
    };
    for (const [file, source] of Object.entries(files)) {
      await mkdir(path.dirname(path.join(root, file)), { recursive: true });
      await writeFile(path.join(root, file), source);
    }
    await expect(
      build({
        configFile: false,
        root,
        plugins: [bundleReport()],
        logLevel: "silent"
      })
    ).rejects.toThrow(new RegExp(`eager.*${scope}`, "i"));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

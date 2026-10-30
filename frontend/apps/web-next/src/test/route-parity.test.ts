import { copyFileSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { afterEach, expect, it } from "vitest";
import { blobHash, nextRoutePath, viteRoutePaths } from "../../scripts/check-route-parity.mjs";

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function tree(routes: string[]) {
  return `export interface FileRoutesByFullPath {\n${routes.map((route) => `  ${JSON.stringify(route)}: unknown`).join("\n")}\n}\n`;
}

function fixture() {
  const root = mkdtempSync(path.join(tmpdir(), "route-parity-"));
  roots.push(root);
  function write(file: string, content: string) {
    mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    writeFileSync(path.join(root, file), content);
  }
  write("src/app/page.tsx", "export default function Page() {}\n");
  write("src/app/layout.tsx", "export default function Layout() {}\n");
  write("src/app/(public)/public-page.tsx", "export const PublicPage = null;\n");
  write("src/proxy.ts", "export const policy = 'nonce';\n");
  write("next.config.ts", "export default {};\n");
  write("src/routeTree.gen.ts", tree(["/", "/$"]));
  write("scripts/route-parity.lock", "");
  copyFileSync(
    path.resolve(import.meta.dirname, "../../scripts/check-route-parity.mjs"),
    path.join(root, "scripts/check-route-parity.mjs")
  );
  function run(...args: string[]) {
    return spawnSync(process.execPath, ["scripts/check-route-parity.mjs", ...args], {
      cwd: root,
      encoding: "utf8"
    });
  }
  const recorded = run(
    "--record",
    "src/app/page.tsx",
    "src/app/layout.tsx",
    "src/proxy.ts",
    "next.config.ts"
  );
  expect(recorded.status, recorded.stderr).toBe(0);
  const lock = () => readFileSync(path.join(root, "scripts/route-parity.lock"), "utf8");
  return { root, write, run, lock };
}

it("uses Git blob hashes, including the byte length and header", () => {
  expect(blobHash(Buffer.from("hello\n"))).toBe("ce013625030ba8dba906f756967f9e9ca394464a");
});

it("normalizes route groups, parameter names, splats and index slashes", () => {
  expect(nextRoutePath("(app)/spaces/[spaceId]/knowledge/collections/[collectionId]")).toBe(
    "/spaces/$/knowledge/collections/$"
  );
  const paths = viteRoutePaths(
    tree(["/dashboard/$assistantId/{-$sessionId}", "/invite/$", "/account", "/account/"])
  );
  expect(paths).toContain(nextRoutePath("(app)/dashboard/[assistantId]/[[...sessionId]]"));
  expect(paths).toContain(nextRoutePath("(public)/invite/[[...rest]]"));
  expect(paths.filter((route: string) => route === "/account")).toHaveLength(1);
  expect(
    viteRoutePaths("interface FileRoutesByFullPath {\n '/users/$userId/': unknown\n}\n")
  ).toEqual(["/users/$"]);
  expect(nextRoutePath("(app)/files/[...path]")).toBe("/files/*");
  expect(nextRoutePath("(app)")).toBe("/");
});

it("checks only exact page/layout names and accepts the documented Vite-only splats", () => {
  const f = fixture();
  f.write(
    "src/routeTree.gen.ts",
    tree([
      "/",
      "/$",
      "/spaces/$spaceId/$",
      "/logout",
      "/module-login/",
      "/login/switch-organisation"
    ])
  );
  const result = f.run("--strict");
  expect(result.status, result.stderr).toBe(0);
  expect(f.lock()).not.toContain("public-page.tsx");
});

it("keeps multiple accepted hashes, records idempotently, and replaces them only on rerecord", () => {
  const f = fixture();
  const original = readFileSync(path.join(f.root, "src/app/page.tsx"), "utf8");
  f.write("src/app/page.tsx", original + "// changed\n");
  expect(f.run("--record", "src/app/page.tsx").status).toBe(0);
  const both = f.lock();
  expect(both.split("\n").filter((line) => line.endsWith("  page.tsx"))).toHaveLength(2);
  expect(f.run("--record", "src/app/page.tsx").status).toBe(0);
  expect(f.lock()).toBe(both);
  expect(f.run().status).toBe(0);
  f.write("src/app/page.tsx", original);
  expect(f.run().status).toBe(0);
  expect(f.run("--rerecord", "src/app/page.tsx").status).toBe(0);
  expect(
    f
      .lock()
      .split("\n")
      .filter((line) => line.endsWith("  page.tsx"))
  ).toHaveLength(1);
  f.write("src/app/page.tsx", original + "// changed\n");
  expect(f.run().status).toBe(1);
});

it("reports unported pages without blocking ordinary lint, but blocks strict mode", () => {
  const f = fixture();
  f.write("src/app/(app)/missing/page.tsx", "export default function Missing() {}\n");
  expect(f.run().status).toBe(0);
  expect(f.run().stdout).toContain("/missing");
  const strict = f.run("--strict");
  expect(strict.status).toBe(1);
  expect(strict.stderr).toContain("/missing");
});

it("requires a snapshot of every layout in strict mode", () => {
  const f = fixture();
  f.write("src/app/(app)/layout.tsx", "export default function AppLayout() {}\n");
  expect(f.run().status).toBe(0);
  const strict = f.run("--strict");
  expect(strict.status).toBe(1);
  expect(strict.stderr).toContain("(app)/layout.tsx");
});

it.each([
  ["src/app/page.tsx", "TanStack"],
  ["src/proxy.ts", "web_app.py"],
  ["next.config.ts", "response_headers.py"]
])("rejects drift in %s and names its actual destination owner", (file, owner) => {
  const f = fixture();
  f.write(file, readFileSync(path.join(f.root, file), "utf8") + " ");
  const result = f.run();
  expect(result.status).toBe(1);
  expect(result.stderr).toContain(path.basename(file));
  expect(result.stderr).toContain(owner);
  expect(result.stderr).toContain("--rerecord");
});

it.each(["page.tsx", "../proxy.ts", "../../next.config.ts"])(
  "rejects an unrecorded required source %s",
  (file) => {
    const f = fixture();
    f.write(
      "scripts/route-parity.lock",
      f
        .lock()
        .split("\n")
        .filter((line) => !line.endsWith(`  ${file}`))
        .join("\n")
    );
    const result = f.run();
    expect(result.status).toBe(1);
    expect(result.stderr).toContain(file);
  }
);

it("rejects a Vite route with neither a Next page nor a documented exception", () => {
  const f = fixture();
  f.write("src/routeTree.gen.ts", tree(["/", "/invented"]));
  const result = f.run();
  expect(result.status).toBe(1);
  expect(result.stderr).toContain("/invented");
});

it("rejects stale and non-route lock paths", () => {
  const f = fixture();
  rmSync(path.join(f.root, "src/app/page.tsx"));
  expect(f.run().status).toBe(1);
  f.write(
    "scripts/route-parity.lock",
    f.lock() + `${blobHash(Buffer.from("x"))}  (public)/public-page.tsx\n`
  );
  const result = f.run();
  expect(result.status).toBe(1);
  expect(result.stderr).toContain("public-page.tsx");
});

it.each(["malformed", "duplicate", "unsupported-route"])(
  "rejects malformed input with exit 2: %s",
  (kind) => {
    const f = fixture();
    if (kind === "malformed") f.write("scripts/route-parity.lock", "not a hash  page.tsx\n");
    if (kind === "duplicate") f.write("scripts/route-parity.lock", f.lock() + f.lock());
    if (kind === "unsupported-route") f.write("src/routeTree.gen.ts", tree(["/", "/users/{id}"]));
    expect(f.run().status).toBe(2);
  }
);

it.each(["src/app/(public)/public-page.tsx", "src/app/missing/page.tsx", "../outside.ts"])(
  "does not record an unsupported file: %s",
  (file) => {
    const f = fixture();
    const before = f.lock();
    expect(f.run("--record", file).status).toBe(2);
    expect(f.lock()).toBe(before);
  }
);

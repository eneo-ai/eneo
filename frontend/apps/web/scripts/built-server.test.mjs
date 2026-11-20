// Runs the built app (`node build`) as its own process and sends it requests
// whose path is not valid percent-encoding. Before the first hook rejected
// them, such a request without a sign-in made the server process exit, and the
// web app stopped answering until it was restarted. Each case here must get
// 400 and leave the same process answering /login.
//
// Needs only `build/` (`bun run build`), no backend: the test owns a local
// stand-in for the backend that answers 503, which the login page tolerates.
// Run with `node --test scripts/built-server.test.mjs` from frontend/apps/web.
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const web = fileURLToPath(new URL("..", import.meta.url));
const START_TIMEOUT_MS = 30_000;
const REQUEST_TIMEOUT_MS = 10_000;
const BAD_PATH_BODY = "Bad Request: the URL path is not valid percent-encoding";

const MALFORMED = [
  { path: "/en/%E0%A4%A" },
  { path: "/%ZZ" },
  { path: "/sv/%C0%AF" },
  { path: "/en/spaces/%ZZ" },
  // adapter-node serves static and prerendered files before the app; these
  // still reach the app and get the same answer.
  { path: "/_app/%ZZ" },
  { path: "/en/%ZZ/__data.json" },
  // A remote-function request carries the page's path in a header, and
  // SvelteKit uses it as the request path.
  { path: "/_app/remote/x1/y", headers: { "x-sveltekit-pathname": "/%ZZ" } }
];

const DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
const PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile";
// A made-up `auth` cookie only selects the signed-in branch of the login
// check; it proves no sign-in, and nothing here needs one.
const SESSION = "auth=made-up-token-not-a-session";

const VISITORS = [
  { name: "without a session cookie", headers: { "user-agent": DESKTOP } },
  { name: "without a session cookie on a phone", headers: { "user-agent": PHONE } },
  { name: "with a session cookie", headers: { "user-agent": DESKTOP, cookie: SESSION } },
  { name: "with a session cookie on a phone", headers: { "user-agent": PHONE, cookie: SESSION } }
];

let server;
let backend;
let origin;
let output = "";
let exited;

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function serverLog() {
  return `server output (last 2000 characters):\n${output.slice(-2000)}`;
}

async function get(path, headers = {}) {
  let response;
  try {
    response = await fetch(`${origin}${path}`, {
      headers,
      redirect: "manual",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
  } catch (error) {
    await Promise.race([exited, delay(2000, undefined, { ref: false })]);
    const state =
      server.exitCode === null && server.signalCode === null
        ? "is still running"
        : `exited (code ${server.exitCode}, signal ${server.signalCode})`;
    throw new Error(
      `GET ${path} got no answer (${error.cause?.code ?? error.name}); the server ${state}.\n${serverLog()}`
    );
  }
  return {
    status: response.status,
    type: response.headers.get("content-type"),
    location: response.headers.get("location"),
    body: await response.text()
  };
}

async function assertStillAnswering(after) {
  const login = await get("/login", { "user-agent": DESKTOP });
  assert.equal(login.status, 200, `/login after ${after}\n${serverLog()}`);
  assert.equal(server.exitCode, null, `the server process exited after ${after}`);
  assert.doesNotThrow(
    () => process.kill(server.pid, 0),
    `pid ${server.pid} is gone after ${after}`
  );
}

before(async () => {
  assert.ok(existsSync(`${web}/build/index.js`), "build/ is missing: run `bun run build` first");
  // Bound for the whole run, so the server's backend calls never reach another
  // process. 503 is an answer the app already handles as "backend unavailable".
  backend = createServer((request, response) => response.writeHead(503).end());
  await new Promise((resolve, reject) => {
    backend.once("error", reject);
    backend.listen(0, "127.0.0.1", resolve);
  });
  const backendUrl = `http://127.0.0.1:${backend.address().port}`;
  const port = await freePort();
  origin = `http://127.0.0.1:${port}`;

  // Only what the server reads at start-up; placeholders, no real values.
  server = spawn(process.execPath, ["build"], {
    cwd: web,
    env: {
      PATH: process.env.PATH,
      NODE_ENV: "production",
      HOST: "127.0.0.1",
      PORT: String(port),
      ORIGIN: origin,
      PUBLIC_ORIGIN: origin,
      ENEO_BACKEND_URL: backendUrl,
      PUBLIC_ENEO_BACKEND_URL: backendUrl,
      JWT_SECRET: "placeholder-for-the-built-server-test"
    },
    stdio: ["ignore", "pipe", "pipe"]
  });
  exited = new Promise((resolve) => server.once("exit", resolve));
  server.stdout.on("data", (chunk) => (output += chunk));
  server.stderr.on("data", (chunk) => (output += chunk));

  const deadline = Date.now() + START_TIMEOUT_MS;
  for (;;) {
    if (server.exitCode !== null) assert.fail(`the server exited at start-up\n${serverLog()}`);
    try {
      const response = await fetch(`${origin}/login`, {
        redirect: "manual",
        signal: AbortSignal.timeout(2000)
      });
      await response.body?.cancel();
      // Only once adapter-node says it listens: a 200 from another process that
      // took the port does not count, and the start-up check above fails instead.
      if (response.status === 200 && output.includes("Listening on")) return;
    } catch {
      // not listening yet
    }
    if (Date.now() > deadline)
      assert.fail(`no 200 from /login within ${START_TIMEOUT_MS} ms\n${serverLog()}`);
    await delay(200);
  }
});

after(async () => {
  if (server && server.exitCode === null && server.signalCode === null) {
    server.kill("SIGTERM");
    // An unref'd timer: once the server has exited it no longer holds the test.
    await Promise.race([exited, delay(5000, undefined, { ref: false })]);
    if (server.exitCode === null && server.signalCode === null) server.kill("SIGKILL");
  }
  backend?.closeAllConnections();
  await new Promise((resolve) => (backend ? backend.close(resolve) : resolve()));
});

test("the built server answers /login with 200 before the probes", async () => {
  const login = await get("/login", { "user-agent": DESKTOP });
  assert.equal(login.status, 200);
  assert.ok(server.pid > 0);
});

for (const visitor of VISITORS) {
  test(`a path that is not valid percent-encoding gets 400 ${visitor.name}, and the server keeps answering`, async () => {
    for (const { path, headers } of MALFORMED) {
      const label = headers ? `${path} ${JSON.stringify(headers)}` : path;
      const response = await get(path, { ...visitor.headers, ...headers });
      assert.equal(response.status, 400, `${label} ${visitor.name}`);
      assert.match(response.type ?? "", /^text\/plain/, `${label} content-type`);
      assert.equal(response.body, BAD_PATH_BODY, `${label} body`);
      await assertStillAnswering(label);
    }
  });
}

test("a path that is valid percent-encoding goes on to the sign-in check unchanged", async () => {
  for (const path of ["/sv/%C3%A5", "/%25ZZ", "/%252F", "/a%2Fb"]) {
    const response = await get(path, { "user-agent": DESKTOP });
    assert.equal(response.status, 302, path);
    assert.equal(response.location, `/login?next=${encodeURIComponent(path)}`, path);
  }
  // The check covers the path only; a query that is not valid encoding is the page's business.
  const login = await get("/login?q=%ZZ", { "user-agent": DESKTOP });
  assert.equal(login.status, 200, "/login?q=%ZZ");
  await assertStillAnswering("the valid paths");
});

test("ordinary requests keep their answers", async () => {
  const home = await get("/", { "user-agent": DESKTOP });
  assert.equal(home.status, 302, "/ without a session");
  assert.equal(home.location, "/login?next=%2F");
  for (const path of ["/sv/login", "/en/login"]) {
    assert.equal((await get(path, { "user-agent": DESKTOP })).status, 200, path);
  }
  const phone = await get("/spaces/personal", { "user-agent": PHONE, cookie: SESSION });
  assert.equal(phone.status, 302, "a page on a phone with a session cookie");
  assert.equal(phone.location, "/dashboard");
});

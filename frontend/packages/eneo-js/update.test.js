import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { test } from "node:test";

import {
  openApiTypescriptArgs,
  parseOptions,
  replaceClientVersion,
  resolveSchemaSource,
  runUpdate
} from "./update.js";

const openapi = JSON.stringify({
  openapi: "3.1.0",
  info: { title: "Eneo", version: "2.0.0" },
  paths: {}
});

function spawnSuccess(calls, order) {
  return (command, args) => {
    calls.push({ command, args });
    order.push(args[0] === "x" ? "spawnSchema" : "spawnFormat");
    const child = new EventEmitter();
    queueMicrotask(() => child.emit("close", 0));
    return child;
  };
}

test("parseOptions rejects conflicting schema-file and local flags", () => {
  assert.throws(
    () => parseOptions(["--schema-file", "/tmp/openapi.json", "--local"]),
    /--schema-file and --local cannot be used together/
  );
});

test("parseOptions supports schema-file equals form and rejects unknown options", () => {
  assert.deepEqual(parseOptions(["--schema-file=/tmp/openapi.json"]), {
    local: false,
    schemaFile: "/tmp/openapi.json"
  });
  assert.throws(() => parseOptions(["--bogus"]), /Unknown option: --bogus/);
});

test("resolveSchemaSource applies schema-file local env default precedence", () => {
  assert.deepEqual(
    resolveSchemaSource(
      { schemaFile: "/tmp/openapi.json", local: false },
      { ENEO_BACKEND_URL: "https://env.example" }
    ),
    { kind: "file", path: "/tmp/openapi.json" }
  );
  assert.deepEqual(
    resolveSchemaSource({ local: true }, { ENEO_BACKEND_URL: "https://env.example" }),
    { kind: "url", url: "http://localhost:8123" }
  );
  assert.deepEqual(
    resolveSchemaSource({ local: false }, { ENEO_BACKEND_URL: "https://eneo.example" }),
    { kind: "url", url: "https://eneo.example" }
  );
});

test("replaceClientVersion updates the existing client version literal", () => {
  assert.equal(
    replaceClientVersion('const version = "1.0.0";\n', "2.0.0"),
    'const version = "2.0.0";\n'
  );
});

test("replaceClientVersion preserves the updater marker comment", () => {
  assert.equal(
    replaceClientVersion(
      '  const version = "DEV"; // # Client version auto-updates when running the updater, do not edit this line.\n',
      "2.0.0"
    ),
    '  const version = "2.0.0"; // # Client version auto-updates when running the updater, do not edit this line.\n'
  );
});

test("replaceClientVersion accepts a current client version", () => {
  assert.equal(
    replaceClientVersion(
      '  const version = "DEV"; // # Client version auto-updates when running the updater, do not edit this line.\n',
      "DEV"
    ),
    '  const version = "DEV"; // # Client version auto-updates when running the updater, do not edit this line.\n'
  );
});

test("openApiTypescriptArgs uses argv array with fixed compatibility option", () => {
  assert.deepEqual(openApiTypescriptArgs("/tmp/openapi.json"), [
    "x",
    "openapi-typescript",
    "/tmp/openapi.json",
    "-o",
    "src/types/schema.d.ts",
    "--default-non-nullable=false"
  ]);
});

test("runUpdate URL mode fetches once and reuses one snapshot", async () => {
  const order = [];
  const spawnCalls = [];
  const writes = new Map();
  const fetchCalls = [];
  const clientFile = "./src/client/client.js";
  const snapshotPath = "/tmp/eneo-openapi-123-456.json";
  let snapshotWriteCount = 0;

  await runUpdate([], {
    env: { ENEO_BACKEND_URL: "https://backend.example" },
    fetch: async (url) => {
      fetchCalls.push(url);
      return {
        ok: true,
        status: 200,
        text: async () => openapi
      };
    },
    fs: {
      readFileSync: (filePath) => {
        if (filePath !== clientFile) {
          throw new Error(`Unexpected read: ${filePath}`);
        }
        order.push("readClient");
        return 'const version = "1.0.0";\n';
      },
      writeFileSync: (filePath, content) => {
        writes.set(filePath, String(content));
        if (filePath === snapshotPath) {
          snapshotWriteCount += 1;
        }
        order.push(filePath === snapshotPath ? "writeSnapshot" : "writeClient");
      }
    },
    spawn: spawnSuccess(spawnCalls, order),
    console: { log() {}, error() {} },
    tmpdir: () => "/tmp",
    now: () => 123,
    pid: 456
  });

  assert.deepEqual(fetchCalls, ["https://backend.example/openapi.json"]);
  assert.equal(snapshotWriteCount, 1);
  assert.equal(writes.get(snapshotPath), openapi);
  assert.equal(writes.get(clientFile), 'const version = "2.0.0";\n');
  assert.equal(spawnCalls[0].command, "bun");
  assert.equal(spawnCalls[0].args[2], snapshotPath);
  assert.equal(order.indexOf("writeSnapshot") < order.indexOf("readClient"), true);
  assert.equal(order.indexOf("writeSnapshot") < order.indexOf("spawnSchema"), true);
});

test("runUpdate schema-file mode does not fetch and passes the file to schema generation", async () => {
  const order = [];
  const spawnCalls = [];
  const schemaFile = "/tmp/canonical-openapi.json";
  const clientFile = "./src/client/client.js";

  await runUpdate(["--schema-file", schemaFile], {
    env: { ENEO_BACKEND_URL: "https://backend.example" },
    fetch: async () => {
      throw new Error("fetch should not be called");
    },
    fs: {
      readFileSync: (filePath) => {
        if (filePath === schemaFile) {
          return openapi;
        }
        if (filePath === clientFile) {
          return 'const version = "1.0.0";\n';
        }
        throw new Error(`Unexpected read: ${filePath}`);
      },
      writeFileSync: () => {}
    },
    spawn: spawnSuccess(spawnCalls, order),
    console: { log() {}, error() {} },
    tmpdir: () => "/tmp",
    now: () => 123,
    pid: 456
  });

  assert.equal(spawnCalls[0].args[2], schemaFile);
});

test("runUpdate reports missing and invalid schema files clearly", async () => {
  await assert.rejects(
    runUpdate(["--schema-file", "/tmp/missing.json"], {
      fs: {
        readFileSync: () => {
          throw new Error("ENOENT");
        },
        writeFileSync: () => {}
      },
      console: { log() {}, error() {} }
    }),
    /Could not read --schema-file \/tmp\/missing\.json/
  );

  await assert.rejects(
    runUpdate(["--schema-file", "/tmp/invalid.json"], {
      fs: {
        readFileSync: () => "{",
        writeFileSync: () => {}
      },
      console: { log() {}, error() {} }
    }),
    /Invalid OpenAPI JSON from \/tmp\/invalid\.json/
  );
});

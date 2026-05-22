#!/usr/bin/env node
/** Regenerates the typed client and schema from a single OpenAPI snapshot. */
import fs from "fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const localUrl = "http://localhost:8123";
const defaultSchemaOutput = "src/types/schema.d.ts";
const defaultClientFile = "./src/client/client.js";

/**
 * @typedef {{ schemaFile?: string, local: boolean }} UpdateOptions
 * @typedef {{ kind: "file", path: string } | { kind: "url", url: string }} SchemaSource
 * @typedef {{
 *   env?: Record<string, string | undefined>,
 *   fetch?: typeof fetch,
 *   fs?: Pick<typeof fs, "readFileSync" | "writeFileSync">,
 *   spawn?: typeof spawn,
 *   console?: Pick<Console, "log" | "error">,
 *   tmpdir?: () => string,
 *   now?: () => number,
 *   pid?: number
 * }} UpdatePorts
 * @typedef {{ snapshotPath: string, openapi: Record<string, unknown> }} OpenApiSnapshot
 */

/** @param {string[]} args @returns {UpdateOptions} */
export function parseOptions(args) {
  /** @type {UpdateOptions} */
  const options = { local: false };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--local") {
      options.local = true;
      continue;
    }
    if (arg === "--schema-file") {
      const value = args[index + 1];
      if (!value || value.startsWith("--")) {
        throw new Error("--schema-file requires a path.");
      }
      options.schemaFile = value;
      index += 1;
      continue;
    }
    if (arg.startsWith("--schema-file=")) {
      const value = arg.slice("--schema-file=".length);
      if (!value) {
        throw new Error("--schema-file requires a path.");
      }
      options.schemaFile = value;
      continue;
    }
    throw new Error(`Unknown option: ${arg}`);
  }

  if (options.schemaFile && options.local) {
    throw new Error("--schema-file and --local cannot be used together.");
  }

  return options;
}

/**
 * @param {UpdateOptions} options
 * @param {Record<string, string | undefined>} env
 * @returns {SchemaSource}
 */
export function resolveSchemaSource(options, env) {
  if (options.schemaFile) {
    return { kind: "file", path: options.schemaFile };
  }
  if (options.local) {
    return { kind: "url", url: localUrl };
  }
  return {
    kind: "url",
    url: env.ENEO_BACKEND_URL || env.INTRIC_BACKEND_URL || localUrl
  };
}

/** @param {string} baseUrl @returns {string} */
function openApiUrl(baseUrl) {
  return `${baseUrl.replace(/\/$/, "")}/openapi.json`;
}

/** @param {string} snapshotPath @returns {string[]} */
export function openApiTypescriptArgs(snapshotPath) {
  return [
    "x",
    "openapi-typescript",
    snapshotPath,
    "-o",
    defaultSchemaOutput,
    // Preserves v6 behavior where properties with defaults remain optional.
    "--default-non-nullable=false"
  ];
}

/** @param {string} clientSource @param {string} version @returns {string} */
export function replaceClientVersion(clientSource, version) {
  const regex = /(?<=const version = ")(.*)(?=";)/;
  const updatedClient = clientSource.replace(regex, version);
  if (updatedClient === clientSource) {
    throw new Error("Could not find client version declaration.");
  }
  return updatedClient;
}

/** @param {unknown} openapi @returns {string} */
function readOpenApiVersion(openapi) {
  const version =
    openapi &&
    typeof openapi === "object" &&
    "info" in openapi &&
    openapi.info &&
    typeof openapi.info === "object" &&
    "version" in openapi.info
      ? openapi.info.version
      : undefined;
  if (typeof version !== "string" || version.length === 0) {
    throw new Error("OpenAPI schema is missing info.version.");
  }
  return version;
}

/**
 * @param {SchemaSource} source
 * @param {Required<Pick<UpdatePorts, "fs" | "fetch" | "tmpdir" | "now" | "pid" | "console">>} ports
 * @returns {Promise<OpenApiSnapshot>}
 */
async function acquireOpenApiSnapshot(source, ports) {
  if (source.kind === "file") {
    let raw;
    try {
      raw = String(ports.fs.readFileSync(source.path));
    } catch (error) {
      throw new Error(`Could not read --schema-file ${source.path}: ${error.message}`);
    }
    return { snapshotPath: source.path, openapi: parseOpenApiJson(raw, source.path) };
  }

  const url = openApiUrl(source.url);
  const response = await ports.fetch(url);
  if (!response.ok) {
    throw new Error(`Could not fetch ${url}: HTTP ${response.status}`);
  }
  const raw = await response.text();
  const snapshotPath = path.join(ports.tmpdir(), `eneo-openapi-${ports.now()}-${ports.pid}.json`);
  ports.fs.writeFileSync(snapshotPath, raw);
  ports.console.log(`Saved OpenAPI snapshot to ${snapshotPath}`);
  return { snapshotPath, openapi: parseOpenApiJson(raw, url) };
}

/** @param {string} raw @param {string} sourceLabel @returns {Record<string, unknown>} */
function parseOpenApiJson(raw, sourceLabel) {
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("OpenAPI root must be an object.");
    }
    return parsed;
  } catch (error) {
    throw new Error(`Invalid OpenAPI JSON from ${sourceLabel}: ${error.message}`);
  }
}

/**
 * @param {Record<string, unknown>} openapi
 * @param {string} clientFile
 * @param {Pick<typeof fs, "readFileSync" | "writeFileSync">} filesystem
 * @param {Pick<Console, "log">} logger
 * @returns {void}
 */
function updateClientFromOpenApi(openapi, clientFile, filesystem, logger) {
  const version = readOpenApiVersion(openapi);
  const client = String(filesystem.readFileSync(clientFile));
  filesystem.writeFileSync(clientFile, replaceClientVersion(client, version));
  logger.log(`Updated client/client.js with current schema version ${version}`);
}

/**
 * @param {string} command
 * @param {string[]} args
 * @param {Required<Pick<UpdatePorts, "spawn">>} ports
 * @returns {Promise<void>}
 */
function runCommand(command, args, ports) {
  return new Promise((resolve, reject) => {
    const child = ports.spawn(command, args, { stdio: "inherit" });

    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} ${args.join(" ")} exited with code ${code}`));
    });

    child.on("error", reject);
  });
}

/** @param {string} snapshotPath @param {Required<Pick<UpdatePorts, "spawn">>} ports */
function updateSchemaFromSnapshot(snapshotPath, ports) {
  return runCommand("bun", openApiTypescriptArgs(snapshotPath), ports);
}

/** @param {Required<Pick<UpdatePorts, "spawn">>} ports */
function runFormatter(ports) {
  return runCommand("bun", ["run", "format"], ports);
}

/** @param {UpdatePorts} ports @returns {Required<UpdatePorts>} */
function withDefaultPorts(ports = {}) {
  return {
    env: ports.env || process.env,
    fetch: ports.fetch || fetch,
    fs: ports.fs || fs,
    spawn: ports.spawn || spawn,
    console: ports.console || console,
    tmpdir: ports.tmpdir || os.tmpdir,
    now: ports.now || Date.now,
    pid: ports.pid || process.pid
  };
}

/** @param {string[]} args @param {UpdatePorts} ports @returns {Promise<void>} */
export async function runUpdate(args = process.argv.slice(2), ports = {}) {
  const resolvedPorts = withDefaultPorts(ports);
  const options = parseOptions(args);
  const source = resolveSchemaSource(options, resolvedPorts.env);

  resolvedPorts.console.log(
    source.kind === "file" ? `Updating from ${source.path}` : `Updating from ${source.url}`
  );

  const snapshot = await acquireOpenApiSnapshot(source, resolvedPorts);
  updateClientFromOpenApi(
    snapshot.openapi,
    defaultClientFile,
    resolvedPorts.fs,
    resolvedPorts.console
  );
  await updateSchemaFromSnapshot(snapshot.snapshotPath, resolvedPorts);
  await runFormatter(resolvedPorts);
  resolvedPorts.console.log("Update completed successfully");
}

async function main() {
  try {
    await runUpdate();
  } catch (error) {
    console.error("Update failed:", error);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}

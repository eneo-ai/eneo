import { lookup } from "node:dns/promises";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { connect } from "node:net";
import ipaddr from "ipaddr.js";
import { allowedDockerHostAddress, type DownloadPolicy } from "./config";
import { ToolError } from "../../errors";

function denied(
  reason = "Check the allowed origins and private-network settings with the operator.",
): never {
  throw new ToolError(
    "DOWNLOAD_DENIED",
    `File URL is not an allowed download destination. ${reason} This is a destination-policy block; it does not establish that the signed URL is invalid or expired.`,
  );
}
export function validateUrl(raw: string, config: Pick<DownloadPolicy, "allowed_origins">): URL {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return denied();
  }
  if (url.username || url.password || url.hash) return denied();
  if (!config.allowed_origins.some((o) => o.origin === url.origin))
    return denied(
      "The attachment origin (scheme, host and port) is not configured for this instance. Ask the operator to add it to the instance's file download sources; allowing private addresses alone does not add an origin.",
    );
  return url;
}
export function addressAllowed(address: string, allowPrivate: boolean, hostname = ""): boolean {
  if (!ipaddr.isValid(address)) return false;
  const parsed = ipaddr.process(address);
  const range = parsed.range();
  return (
    range === "unicast" ||
    (allowPrivate && ["private", "loopback", "uniqueLocal"].includes(range)) ||
    allowedDockerHostAddress(parsed.toString(), hostname, allowPrivate)
  );
}

/** Resolves a validated URL's host and enforces the address policy on every answer. */
async function resolvePinned(url: URL, config: DownloadPolicy, signal: AbortSignal) {
  const allowPrivate = config.allowed_origins.find((o) => o.origin === url.origin)!.allow_private;
  const hostname = url.hostname.replace(/^\[|\]$/g, "");
  // The actual socket uses this checked address, avoiding a second DNS resolution.
  const addresses = await new Promise<{ address: string; family: number }[]>((resolve, reject) => {
    const abort = () => reject(new Error("Download timed out"));
    if (signal.aborted) {
      abort();
      return;
    }
    signal.addEventListener("abort", abort, { once: true });
    lookup(hostname, { all: true })
      .then(resolve, reject)
      .catch(() => reject(new Error(`ENOTFOUND ${hostname}`)))
      .finally(() => signal.removeEventListener("abort", abort));
  });
  if (
    !addresses.length ||
    addresses.some((a) => !addressAllowed(a.address, allowPrivate, hostname))
  )
    return denied();
  return { hostname, pinned: addresses[0]! };
}
/** The operator-facing reason a fetch failed, without the signed URL. */
function downloadError(error: unknown, hostname: string): ToolError {
  if (error instanceof ToolError) return error;
  const message = error instanceof Error ? error.message : String(error);
  const code = (error as { code?: string })?.code ?? "";
  const status = /^response:(\d+)$/.exec(message)?.[1];
  if (status)
    return new ToolError(
      "DOWNLOAD_FAILED",
      `${hostname} answered the download with HTTP ${status}. The signed URL was refused: use the url from the file's attachment reference in the current request, exactly as given. Links copied from earlier tool calls do not work. Do not ask the user to upload the file again.`,
    );
  if (message === "Download timed out" || message === "timeout" || code === "ETIMEDOUT")
    return new ToolError(
      "DOWNLOAD_FAILED",
      `The download from ${hostname} timed out before finishing. Check that the host is reachable from the tool runtime and try again.`,
    );
  if (
    /^E(NOTFOUND|AI_AGAIN|CONNREFUSED|HOSTUNREACH|NETUNREACH|CONNRESET|PIPE)$/.test(code) ||
    message.startsWith("ENOTFOUND")
  )
    return new ToolError(
      "DOWNLOAD_UNREACHABLE",
      `${hostname} cannot be reached from the tool runtime (${code || "no route"}). The file origin must be reachable from the network the tool runtime runs in; this is not a problem with the signed URL.`,
    );
  return new ToolError(
    "DOWNLOAD_FAILED",
    "Could not download the file. Check that its signed URL is valid and unexpired.",
  );
}
const PROBE_TIMEOUT_MS = 3000;
/**
 * Checks that a file URL's host can be reached at all, so an unreachable origin fails at intake
 * instead of in the worker a moment later. Only a TCP connection is made: the signed URL is
 * never requested here, and reachability is a network fact that does not change between the
 * gateway and the worker in a supported deployment.
 */
export async function probeUrl(raw: string, config: DownloadPolicy): Promise<void> {
  const url = validateUrl(raw, config);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  let hostname = url.hostname;
  try {
    const resolved = await resolvePinned(url, config, controller.signal);
    hostname = resolved.hostname;
    const port = Number(url.port) || (url.protocol === "https:" ? 443 : 80);
    await new Promise<void>((resolve, reject) => {
      const socket = connect({
        host: resolved.pinned.address,
        port,
        family: resolved.pinned.family,
        signal: controller.signal,
      });
      socket.once("connect", () => {
        socket.destroy();
        resolve();
      });
      socket.once("error", (error) => {
        socket.destroy();
        reject(error);
      });
    });
  } catch (error) {
    const aborted =
      (error as { name?: string })?.name === "AbortError" || controller.signal.aborted;
    throw downloadError(aborted ? new Error("timeout") : error, hostname);
  } finally {
    clearTimeout(timer);
  }
}

export async function downloadFile(
  raw: string,
  config: DownloadPolicy,
): Promise<{ bytes: Buffer; contentType: string; name: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.download_timeout_ms);
  let hostname = "";
  try {
    let url = validateUrl(raw, config);
    for (let hop = 0; hop <= 3; hop++) {
      const resolved = await resolvePinned(url, config, controller.signal);
      hostname = resolved.hostname;
      const pinned = resolved.pinned;
      if (controller.signal.aborted) throw new Error("timeout");
      const response = await new Promise<{ redirect?: string; bytes: Buffer; contentType: string }>(
        (resolve, reject) => {
          const transport = url.protocol === "https:" ? httpsRequest : httpRequest;
          const req = transport(
            url,
            {
              signal: controller.signal,
              headers: { "accept-encoding": "identity" },
              lookup: (_hostname, options, callback) => {
                if (options.all) callback(null, [pinned]);
                else callback(null, pinned.address, pinned.family);
              },
            },
            (res) => {
              if ([301, 302, 303, 307, 308].includes(res.statusCode ?? 0)) {
                const location = res.headers.location;
                res.destroy();
                if (!location) reject(new Error("redirect"));
                else resolve({ redirect: location, bytes: Buffer.alloc(0), contentType: "" });
                return;
              }
              if (
                res.statusCode !== 200 ||
                (res.headers["content-encoding"] && res.headers["content-encoding"] !== "identity")
              ) {
                res.destroy();
                reject(new Error(`response:${res.statusCode ?? 0}`));
                return;
              }
              if (Number(res.headers["content-length"] ?? 0) > config.max_upload_bytes) {
                res.destroy();
                reject(new ToolError("FILE_TOO_LARGE", "File exceeds the upload size limit."));
                return;
              }
              const chunks: Buffer[] = [];
              let size = 0;
              res.on("data", (chunk: Buffer) => {
                size += chunk.length;
                if (size > config.max_upload_bytes) {
                  res.destroy();
                  reject(new ToolError("FILE_TOO_LARGE", "File exceeds the upload size limit."));
                } else chunks.push(chunk);
              });
              res.on("error", reject);
              res.on("end", () =>
                resolve({
                  bytes: Buffer.concat(chunks),
                  contentType: String(res.headers["content-type"] ?? "").split(";")[0]!,
                }),
              );
            },
          );
          req.on("error", reject);
          req.end();
        },
      );
      if (response.redirect) {
        url = validateUrl(new URL(response.redirect, url).href, config);
        continue;
      }
      if (!response.bytes.length)
        throw new ToolError("EMPTY_FILE", "The downloaded file is empty.");
      return {
        ...response,
        name: decodeURIComponent(url.pathname.split("/").pop() || "file").slice(0, 200),
      };
    }
    throw new ToolError("DOWNLOAD_FAILED", "Too many download redirects.");
  } catch (error) {
    // An aborted socket reports a reset; the deadline is the real cause.
    throw downloadError(
      controller.signal.aborted && !(error instanceof ToolError) ? new Error("timeout") : error,
      hostname || new URL(raw).hostname,
    );
  } finally {
    clearTimeout(timer);
  }
}

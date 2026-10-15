import { describe, expect, test } from "bun:test";
import { tabularConfigSchema, type DownloadPolicy } from "../../src/tools/tabular/config";
import {
  addressAllowed,
  downloadFile,
  probeUrl,
  validateUrl,
} from "../../src/tools/tabular/download";

function policy(
  allowed_origins: DownloadPolicy["allowed_origins"],
  limits: Partial<Pick<DownloadPolicy, "max_upload_bytes" | "download_timeout_ms">> = {},
): DownloadPolicy {
  return { ...tabularConfigSchema.parse(limits), allowed_origins };
}

describe("URL intake boundaries", () => {
  test("denies private and metadata addresses unless specifically eligible", () => {
    expect(addressAllowed("127.0.0.1", false)).toBe(false);
    expect(addressAllowed("127.0.0.1", true)).toBe(true);
    expect(addressAllowed("::ffff:127.0.0.1", false)).toBe(false);
    expect(addressAllowed("169.254.169.254", true)).toBe(false);
    expect(addressAllowed("0.0.0.0", true)).toBe(false);
    expect(addressAllowed("10.0.0.1", false)).toBe(false);
  });
  test("allows Docker's synthetic host only with its hostname and private access", () => {
    expect(addressAllowed("0.250.250.254", true, "host.docker.internal")).toBe(true);
    expect(addressAllowed("::ffff:0.250.250.254", true, "host.docker.internal")).toBe(true);
    expect(addressAllowed("0.250.250.254", false, "host.docker.internal")).toBe(false);
    for (const hostname of ["", "0.250.250.254", "files.example", "host.docker.internal.evil"])
      expect(addressAllowed("0.250.250.254", true, hostname)).toBe(false);
    for (const address of ["0.250.250.253", "0.0.0.0", "169.254.169.254", "fe80::1"])
      expect(addressAllowed(address, true, "host.docker.internal")).toBe(false);
  });
  test("validates exact origins and rejects URL credentials", () => {
    const config = policy([{ origin: "https://files.example", allow_private: false }]);
    expect(() => validateUrl("https://files.example.evil/x", config)).toThrow();
    expect(() => validateUrl("https://user:password@files.example/x", config)).toThrow();
    const local = policy([{ origin: "http://host.docker.internal:8123", allow_private: true }]);
    expect(
      validateUrl("http://host.docker.internal:8123/original/download?token=test-secret", local)
        .port,
    ).toBe("8123");
    try {
      validateUrl("http://host.docker.internal:8000/original/download?token=test-secret", local);
      throw new Error("Expected the unconfigured port to be rejected");
    } catch (error) {
      expect((error as Error).message).toContain("scheme, host and port");
      expect((error as Error).message).not.toContain("test-secret");
    }
  });
  test("rejects unsafe redirects, large streaming responses and expired signed links", async () => {
    const server = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch(req) {
        if (req.url.endsWith("redirect"))
          return new Response(null, {
            status: 302,
            headers: { location: "http://169.254.169.254/latest/meta-data" },
          });
        if (req.url.endsWith("expired"))
          return new Response("secret signed-url diagnostics", { status: 403 });
        return new Response(
          new ReadableStream({
            start(c) {
              c.enqueue(new TextEncoder().encode("a".repeat(2048)));
              c.close();
            },
          }),
          { headers: { "content-type": "text/csv" } },
        );
      },
    });
    try {
      const origin = `http://127.0.0.1:${server.port}`;
      const config = policy([{ origin, allow_private: true }], { max_upload_bytes: 100 });
      await expect(downloadFile(`${origin}/redirect`, config)).rejects.toThrow(
        "allowed download destination",
      );
      await expect(downloadFile(`${origin}/large`, config)).rejects.toThrow("size limit");
      await expect(downloadFile(`${origin}/expired`, config)).rejects.toThrow("HTTP 403");
      await expect(downloadFile(`${origin}/expired`, config)).rejects.not.toThrow("diagnostics");
    } finally {
      await server.stop(true);
    }
  });
  test("names an unreachable origin as a network problem, at intake and at download", async () => {
    const closed = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("x") });
    const origin = `http://127.0.0.1:${closed.port}`;
    await closed.stop(true);
    const config = policy([{ origin, allow_private: true }]);
    await expect(probeUrl(`${origin}/file.csv?token=secret`, config)).rejects.toThrow(
      "cannot be reached from the tool runtime",
    );
    await expect(probeUrl(`${origin}/file.csv?token=secret`, config)).rejects.not.toThrow("secret");
    await expect(downloadFile(`${origin}/file.csv`, config)).rejects.toThrow(
      "cannot be reached from the tool runtime",
    );
    const open = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("x") });
    try {
      const reachable = `http://127.0.0.1:${open.port}`;
      await probeUrl(`${reachable}/file.csv`, policy([{ origin: reachable, allow_private: true }]));
      await expect(
        probeUrl(
          `${reachable}/file.csv`,
          policy([{ origin: "http://other.example", allow_private: false }]),
        ),
      ).rejects.toThrow("allowed download destination");
    } finally {
      await open.stop(true);
    }
  });
  test("applies its deadline to the response body, not only headers", async () => {
    const server = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch: () =>
        new Response(
          new ReadableStream({
            start(c) {
              c.enqueue(new TextEncoder().encode("a,b\n"));
            },
          }),
          { headers: { "content-type": "text/csv" } },
        ),
    });
    try {
      const origin = `http://127.0.0.1:${server.port}`;
      const config = policy([{ origin, allow_private: true }], { download_timeout_ms: 100 });
      await expect(downloadFile(`${origin}/stall`, config)).rejects.toThrow("timed out");
    } finally {
      await server.stop(true);
    }
  });
});

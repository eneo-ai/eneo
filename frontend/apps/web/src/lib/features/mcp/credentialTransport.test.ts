import { describe, expect, it } from "vitest";

import { sendsCredentialOverPlainHttp } from "./credentialTransport";

describe("sendsCredentialOverPlainHttp", () => {
  // Kills: warning on https, missing either credential type, dropping a
  // loopback host (IPv6 included), matching the host by prefix, warning for
  // auth types that send no admin credential, ignoring a user name and
  // password in the URL, and throwing on a half-typed URL.
  it.each([
    ["bearer", "http://mcp.example.org/mcp", true],
    ["api_key_header", "http://mcp.example.org/mcp", true],
    ["bearer", "https://mcp.example.org/mcp", false],
    ["bearer", "http://localhost:8080/mcp", false],
    ["bearer", "http://127.0.0.1/mcp", false],
    ["api_key_header", "http://[::1]:9000/mcp", false],
    ["bearer", "http://localhost.evil.example/mcp", true],
    ["none", "http://mcp.example.org/mcp", false],
    ["none", "http://alice:hunter2@mcp.example.org/mcp", true],
    ["internal", "http://backend:8000/internal-mcp/image_generation/mcp", false],
    ["bundled", "http://tool-runtime:8080/mcp/compute", false],
    ["bearer", "http://", false]
  ])("%s at %s -> %s", (authType, url, expected) => {
    expect(sendsCredentialOverPlainHttp(authType, url)).toBe(expected);
  });
});

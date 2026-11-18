import { describe, expect, it } from "vitest";
import { sendsCredentialOverPlainHttp } from "./credential-transport";

describe("MCP credential transport parity", () => {
  it.each([
    ["bearer", "http://mcp.example/mcp", true],
    ["api_key_header", "http://mcp.example/mcp", true],
    ["future-auth", "http://mcp.example/mcp", true],
    ["bearer", "https://mcp.example/mcp", false],
    ["bearer", "http://localhost:8080/mcp", false],
    ["bearer", "http://127.0.0.1/mcp", false],
    ["api_key_header", "http://[::1]:9000/mcp", false],
    ["bearer", "http://localhost.evil.example/mcp", true],
    ["none", "http://mcp.example/mcp", false],
    ["none", "http://synthetic:fixture@mcp.example/mcp", true],
    ["internal", "http://backend:8000/internal-mcp/image_generation/mcp", false],
    ["bundled", "http://tool-runtime:8080/mcp/compute", false],
    ["bundled", "http://synthetic@tool-runtime:8080/mcp", true],
    ["bearer", "http://", false]
  ])("%s at %s => %s", (auth, url, expected) => {
    expect(sendsCredentialOverPlainHttp(auth, url)).toBe(expected);
  });
});

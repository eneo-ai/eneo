import { describe, expect, it } from "vitest";
import { makeStep } from "../flow-fixtures";
import { connectionToOpen, stepConnections } from "./connections";

const STORED = { $secret: "stored" as const };

describe("stepConnections", () => {
  it("names where a step reads from and delivers to, and whether its secrets are stored", () => {
    const step = makeStep(2, {
      input_source: "http_get",
      input_config: {
        url: "https://api.example.se/cases?key=hidden",
        auth: { mode: "api_key", header_name: "X-Key", key: STORED },
        custom_headers: [{ name: "X-Signature", value: STORED, secret: true }]
      },
      output_mode: "http_post",
      output_config: {
        url: "https://hooks.example.se/in",
        auth: { mode: "bearer_token", token: "" }
      }
    });
    expect(stepConnections(step)).toEqual([
      {
        direction: "input",
        anchor: "input_config.http",
        host: "api.example.se",
        authMode: "api_key",
        configured: true
      },
      {
        direction: "output",
        anchor: "output_config.http",
        host: "hooks.example.se",
        authMode: "bearer_token",
        configured: false
      }
    ]);
  });

  it("treats an open delivery as configured once it has an address, and a missing secret header as not", () => {
    const open = makeStep(2, {
      output_mode: "http_post",
      output_config: { url: "https://hooks.example.se/in", auth: { mode: "none" } }
    });
    expect(stepConnections(open)[0]).toMatchObject({ authMode: "none", configured: true });
    const header = makeStep(2, {
      output_mode: "http_post",
      output_config: {
        url: "https://hooks.example.se/in",
        auth: { mode: "none" },
        custom_headers: [{ name: "X-Signature", value: "", secret: true }]
      }
    });
    expect(stepConnections(header)[0]).toMatchObject({ configured: false });
    expect(stepConnections(makeStep(2, { output_mode: "http_post" }))[0]).toMatchObject({
      host: "",
      configured: false
    });
    expect(stepConnections(makeStep(1))).toEqual([]);
  });

  it("opens the first connection still to configure, else the first", () => {
    const stored = {
      direction: "input",
      anchor: "input_config.http",
      host: "a",
      authMode: "none",
      configured: true
    } as const;
    const missing = {
      ...stored,
      direction: "output",
      anchor: "output_config.http",
      configured: false
    } as const;
    expect(connectionToOpen([stored, missing])).toBe(missing);
    expect(connectionToOpen([stored])).toBe(stored);
    expect(connectionToOpen([])).toBeNull();
  });
});

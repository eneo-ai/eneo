import { expect, it, vi } from "vitest";
import { liveSocketUrl } from "./runs-api";

const config = vi.hoisted(() => ({ base: "" }));
vi.mock("@/lib/api/base", async (original) => ({
  ...(await original<typeof import("@/lib/api/base")>()),
  get API_BASE() {
    return config.base;
  }
}));

it.each([
  ["", "http:", "ws://eneo.test:3101/api/v1/flows/live-transcription/ws"],
  ["", "https:", "wss://eneo.test:3101/api/v1/flows/live-transcription/ws"],
  ["/api/eneo", "https:", "wss://eneo.test:3101/api/eneo/api/v1/flows/live-transcription/ws"]
])(
  "uses the shared API base %s and %s protocol for the live socket",
  (base, protocol, expected) => {
    config.base = base;
    expect(
      liveSocketUrl("/api/v1/flows/live-transcription/ws", { protocol, host: "eneo.test:3101" })
    ).toBe(expected);
  }
);

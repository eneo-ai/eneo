/**
 * Test support for the chat stream contract (CONTRACT.md): loads the shared
 * fixtures and frames them as the SSE body the backend sends. Imported by
 * tests only.
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

/** One fixture file under backend/tests/fixtures/ui_message_stream/. */
export type StreamFixture = {
  name: string;
  description: string;
  /** How the stream ends: `finish` part, `error` part, or cut off (no terminal part). */
  terminal: "finish" | "error" | "truncated";
  /** The JSON payloads of the `data:` events, in order. */
  events: Record<string, unknown>[];
  /** The pinned SDK's projection once the request settled. */
  ui: {
    status: "ready" | "error";
    error?: { message: string; code: number | null };
    message: { id: string; role: "assistant"; parts: Record<string, unknown>[] };
  };
};

export const FIXTURE_DIR = path.resolve(
  import.meta.dirname,
  "../../../../../../backend/tests/fixtures/ui_message_stream"
);

export function loadFixtures(): StreamFixture[] {
  return readdirSync(FIXTURE_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => JSON.parse(readFileSync(path.join(FIXTURE_DIR, file), "utf8")) as StreamFixture);
}

/** Frames events as the backend does: `data: <json>` per event, `data: [DONE]` last. */
export function toSseBody(events: unknown[], { done = true } = {}): string {
  const lines = events.map((event) => `data: ${JSON.stringify(event)}\n\n`);
  return lines.join("") + (done ? "data: [DONE]\n\n" : "");
}

/** The response the /api/chat proxy relays, with the protocol marker header. */
export function sseResponse(body: string | ReadableStream<Uint8Array>): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "x-vercel-ai-ui-message-stream": "v1"
    }
  });
}

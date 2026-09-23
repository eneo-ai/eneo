import { vi } from "vitest";

import type { FlowLiveTranscriptionSession } from "@eneo/eneo-js";
import { PCM16_FLUSH, PCM16_FLUSHED } from "./pcm16-worklet.js";

// Test doubles for the live transcript preview's browser APIs.

export const liveSession: FlowLiveTranscriptionSession = {
  ticket: "t0k3n",
  websocket_path: "/api/v1/flows/live-transcription",
  subprotocol: "eneo-live.v1",
  sample_rate: 16000,
  max_seconds: 18000,
  expires_at: "2026-09-23T10:15:30Z",
  model: { id: "model-1", name: "Pianissimo" }
};

// The browser's WebSocket as the preview sees it; the test plays the server.
export class FakeLiveSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeLiveSocket[] = [];

  readyState = FakeLiveSocket.CONNECTING;
  bufferedAmount = 0;
  sent: Array<string | ArrayBuffer> = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = FakeLiveSocket.CLOSED;
  });

  constructor(
    readonly url: string,
    readonly protocols: string[]
  ) {
    FakeLiveSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }

  open() {
    this.readyState = FakeLiveSocket.OPEN;
    this.onopen?.();
  }

  receive(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  drop() {
    this.readyState = FakeLiveSocket.CLOSED;
    this.onclose?.({ code: 1006 });
  }

  get frames() {
    return this.sent.filter((message) => message instanceof ArrayBuffer);
  }

  get texts() {
    return this.sent.filter((message) => typeof message === "string");
  }
}

// The worklet node. `frame(tag)` is the processor posting 100 ms of audio whose
// first byte is `tag`, so a test can tell frames apart; like a live processor it
// answers a flush request, unless `answersFlush` is turned off.
export class FakeWorkletNode {
  static instances: FakeWorkletNode[] = [];

  answersFlush = true;
  port = {
    onmessage: null as ((event: { data: unknown }) => void) | null,
    postMessage: vi.fn((message: unknown) => {
      if (message === PCM16_FLUSH && this.answersFlush) {
        queueMicrotask(() => this.post(PCM16_FLUSHED));
      }
    }),
    close: vi.fn()
  };

  constructor(
    readonly context: unknown,
    readonly name: string
  ) {
    FakeWorkletNode.instances.push(this);
  }

  frame(tag = 0, bytes = 3200) {
    const frame = new ArrayBuffer(bytes);
    new Uint8Array(frame)[0] = tag;
    this.post(frame);
  }

  post(data: unknown) {
    this.port.onmessage?.({ data });
  }
}

export function frameTags(socket: FakeLiveSocket): number[] {
  return socket.frames.map((frame) => new Uint8Array(frame as ArrayBuffer)[0]);
}

export function installLiveTranscriptFakes() {
  FakeLiveSocket.instances = [];
  FakeWorkletNode.instances = [];
  vi.stubGlobal("WebSocket", FakeLiveSocket);
  vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
}

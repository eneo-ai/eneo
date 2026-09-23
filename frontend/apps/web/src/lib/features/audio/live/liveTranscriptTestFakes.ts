import { vi } from "vitest";

import type { FlowLiveTranscriptionSession } from "@eneo/eneo-js";

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

// The worklet node; `frame()` is the processor posting 100 ms of audio.
export class FakeWorkletNode {
  static instances: FakeWorkletNode[] = [];

  port = {
    onmessage: null as ((event: { data: ArrayBuffer }) => void) | null,
    close: vi.fn()
  };

  constructor(
    readonly context: unknown,
    readonly name: string
  ) {
    FakeWorkletNode.instances.push(this);
  }

  frame() {
    this.port.onmessage?.({ data: new ArrayBuffer(3200) });
  }
}

export function installLiveTranscriptFakes() {
  FakeLiveSocket.instances = [];
  FakeWorkletNode.instances = [];
  vi.stubGlobal("WebSocket", FakeLiveSocket);
  vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
}

import { vi } from "vitest";
import type { LiveTicket, RecorderAudioGraph } from "../live-transcript";

/** Test doubles for the live transcript's browser APIs; the test plays the server. */

export const TICKET: LiveTicket = { ticket: "t0k3n", websocket_path: "/api/v1/live-transcription" };

export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeSocket[] = [];

  readyState = FakeSocket.CONNECTING;
  bufferedAmount = 0;
  binaryType = "blob";
  sent: (string | ArrayBuffer)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn(() => {
    this.readyState = FakeSocket.CLOSED;
  });

  constructor(
    readonly url: string,
    readonly protocols: string[]
  ) {
    FakeSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }

  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  receive(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  drop() {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.();
  }

  get texts(): unknown[] {
    return this.sent.filter((item) => typeof item === "string").map((item) => JSON.parse(item));
  }

  get frameTags(): number[] {
    return this.sent
      .filter((item): item is ArrayBuffer => item instanceof ArrayBuffer)
      .map((frame) => new Uint8Array(frame)[0] ?? -1);
  }
}

/** The worklet node: `frame(tag)` is the processor posting 100 ms of audio starting with `tag`. */
export class FakeNode {
  static instances: FakeNode[] = [];
  port = {
    onmessage: null as ((event: { data: unknown }) => void) | null,
    postMessage: vi.fn((message: unknown) => {
      if (message === "flush") queueMicrotask(() => this.post("flushed"));
      if (message === "resume") queueMicrotask(() => this.post("resumed"));
    }),
    close: vi.fn()
  };

  constructor() {
    FakeNode.instances.push(this);
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

export function fakeGraph(): RecorderAudioGraph {
  const context = Object.assign(new EventTarget(), {
    state: "running",
    audioWorklet: { addModule: vi.fn(() => Promise.resolve()) }
  });
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  return {
    context: context as unknown as AudioContext,
    source: source as unknown as MediaStreamAudioSourceNode
  };
}

export function installLiveFakes() {
  FakeSocket.instances = [];
  FakeNode.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
}

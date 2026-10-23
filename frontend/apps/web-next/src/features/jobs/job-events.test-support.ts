import { vi } from "vitest";

/**
 * A stand-in for the browser's EventSource that a test drives by hand:
 * `open()` connects, `job(data)` pushes an update, `blip()` is a dropped
 * connection the browser retries on its own, `refuse()` is a server refusal
 * (the browser gives up). jsdom has no EventSource, so without this the feed
 * never opens and the jobs hook falls back to polling.
 */
export class FakeEventSource extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = FakeEventSource.CONNECTING;
  closed = false;
  constructor(public url: string) {
    super();
    FakeEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
  open() {
    this.readyState = FakeEventSource.OPEN;
    this.dispatchEvent(new Event("open"));
  }
  job(data: unknown) {
    this.dispatchEvent(new MessageEvent("job", { data: JSON.stringify(data) }));
  }
  blip() {
    this.readyState = FakeEventSource.CONNECTING;
    this.dispatchEvent(new Event("error"));
  }
  refuse() {
    this.readyState = FakeEventSource.CLOSED;
    this.dispatchEvent(new Event("error"));
  }
}

/** Replace the global EventSource for one test; call `restore()` after it. */
export function installFakeEventSource() {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  return {
    latest: () => FakeEventSource.instances.at(-1)!,
    instances: () => FakeEventSource.instances,
    restore: () => vi.unstubAllGlobals()
  };
}

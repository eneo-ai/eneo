import { describe, expect, it, vi } from "vitest";
import { ScreenWakeLock } from "./screenWakeLock";

// A wake lock as the browser hands it out: released by the page or by the browser.
class FakeLock extends EventTarget {
  release = vi.fn(async () => {
    this.dispatchEvent(new Event("release"));
  });
}

function fakes() {
  const locks: FakeLock[] = [];
  let answer: (() => void) | null = null;
  let delayed = false;
  const host = {
    request: vi.fn(async () => {
      if (delayed) await new Promise<void>((resolve) => (answer = resolve));
      const lock = new FakeLock();
      locks.push(lock);
      return lock;
    })
  };
  const page = Object.assign(new EventTarget(), {
    visibilityState: "visible" as DocumentVisibilityState
  });
  const show = (state: DocumentVisibilityState) => {
    page.visibilityState = state;
    page.dispatchEvent(new Event("visibilitychange"));
  };
  return {
    host,
    page: page as unknown as Document,
    locks,
    show,
    delay: () => (delayed = true),
    answer: () => answer?.()
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("ScreenWakeLock", () => {
  it("takes a new lock when the browser released it and the page is visible again", async () => {
    const { host, page, locks, show } = fakes();
    const lock = new ScreenWakeLock(host, page);

    lock.hold();
    await settle();
    expect(host.request).toHaveBeenCalledTimes(1);

    // Hidden, the browser releases the lock itself.
    show("hidden");
    locks[0]?.dispatchEvent(new Event("release"));
    show("visible");
    await settle();
    expect(host.request).toHaveBeenCalledTimes(2);

    lock.release();
    await settle();
    expect(locks[1]?.release).toHaveBeenCalledOnce();
  });

  it("asks again when the browser releases the lock while the page stays visible, a few times at most", async () => {
    const { host, page, locks } = fakes();
    const lock = new ScreenWakeLock(host, page);

    lock.hold();
    await settle();
    for (let release = 0; release < 5; release += 1) {
      locks.at(-1)?.dispatchEvent(new Event("release"));
      await settle();
    }
    expect(host.request).toHaveBeenCalledTimes(3);
    lock.release();
  });

  it("asks again after a pending request when the page became visible meanwhile", async () => {
    const { host, page, show, delay, answer } = fakes();
    delay();
    const lock = new ScreenWakeLock(host, page);

    lock.hold();
    show("hidden");
    show("visible");
    expect(host.request).toHaveBeenCalledTimes(1);
    answer();
    await settle();
    // The first lock is held: the pending visible change needs no second one.
    expect(host.request).toHaveBeenCalledTimes(1);
    lock.release();
  });

  it("asks once while a request is pending, and gives back a lock granted after release", async () => {
    const { host, page, locks, show, delay, answer } = fakes();
    delay();
    const lock = new ScreenWakeLock(host, page);

    lock.hold();
    show("visible");
    show("visible");
    expect(host.request).toHaveBeenCalledTimes(1);

    lock.release();
    answer();
    await settle();
    expect(locks[0]?.release).toHaveBeenCalledOnce();
  });

  it("asks again when a pending request fails after the page became visible again", async () => {
    let refuse: (reason: Error) => void = () => {};
    const locks: FakeLock[] = [];
    const host = {
      request: vi
        .fn()
        .mockImplementationOnce(() => new Promise((_, reject) => (refuse = reject)))
        .mockImplementation(async () => {
          const lock = new FakeLock();
          locks.push(lock);
          return lock;
        })
    };
    const page = Object.assign(new EventTarget(), {
      visibilityState: "visible" as DocumentVisibilityState
    });
    const lock = new ScreenWakeLock(host, page as unknown as Document);

    lock.hold();
    page.visibilityState = "hidden";
    page.dispatchEvent(new Event("visibilitychange"));
    page.visibilityState = "visible";
    page.dispatchEvent(new Event("visibilitychange"));
    refuse(new Error("NotAllowedError"));
    await settle();

    expect(host.request).toHaveBeenCalledTimes(2);
    expect(locks).toHaveLength(1);
    lock.release();
  });

  it("gives every new recording its own lock on the same visible page", async () => {
    const { host, page } = fakes();
    const lock = new ScreenWakeLock(host, page);
    for (let recording = 0; recording < 4; recording += 1) {
      lock.hold();
      await settle();
      lock.release();
    }
    expect(host.request).toHaveBeenCalledTimes(4);
  });

  it("does nothing where the browser has no wake lock", () => {
    const lock = new ScreenWakeLock(undefined, undefined);
    expect(() => {
      lock.hold();
      lock.release();
    }).not.toThrow();
  });
});

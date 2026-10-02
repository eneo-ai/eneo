import { describe, expect, it } from "vitest";
import {
  awaitPartnerUpdates,
  hasPendingPartnerUpdates,
  trackPartnerUpdate
} from "./partner-updates";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("partner updates", () => {
  it("waits for every save in flight, failed ones included, then reports none pending", async () => {
    expect(hasPendingPartnerUpdates()).toBe(false);
    const first = deferred<string>();
    const second = deferred<string>();
    expect(trackPartnerUpdate(first.promise)).toBe(first.promise);
    trackPartnerUpdate(second.promise).catch(() => {});
    expect(hasPendingPartnerUpdates()).toBe(true);

    let settled = false;
    const waiting = awaitPartnerUpdates().then(() => {
      settled = true;
    });
    first.resolve("ok");
    await Promise.resolve();
    expect(settled).toBe(false);

    second.reject(new Error("nope"));
    await waiting;
    expect(settled).toBe(true);
    expect(hasPendingPartnerUpdates()).toBe(false);
  });

  it("resolves at once when nothing is saving", async () => {
    await expect(awaitPartnerUpdates()).resolves.toBeUndefined();
  });
});

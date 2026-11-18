import { describe, expect, it } from "vitest";
import {
  awaitPartnerUpdates,
  hasPendingPartnerUpdates,
  queuePartnerUpdate
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

/** Lets every settled promise run its handlers. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("partner updates", () => {
  it("waits for every save in flight, failed ones included, then reports none pending", async () => {
    expect(hasPendingPartnerUpdates()).toBe(false);
    const first = deferred<string>();
    const second = deferred<string>();
    const saved = queuePartnerUpdate(() => first.promise);
    queuePartnerUpdate(() => second.promise).catch(() => {});
    expect(hasPendingPartnerUpdates()).toBe(true);

    let settled = false;
    const waiting = awaitPartnerUpdates().then(() => {
      settled = true;
    });
    first.resolve("ok");
    await expect(saved).resolves.toBe("ok");
    expect(settled).toBe(false);

    second.reject(new Error("nope"));
    await waiting;
    expect(settled).toBe(true);
    expect(hasPendingPartnerUpdates()).toBe(false);
  });

  it("runs one save at a time, in the order they were made, so an older one never lands last", async () => {
    const order: string[] = [];
    const first = deferred<string>();
    const model = queuePartnerUpdate(() => {
      order.push("model");
      return first.promise;
    });
    const skills = queuePartnerUpdate(async () => {
      order.push("skills");
      return "skills";
    });
    await flush();
    expect(order).toEqual(["model"]);

    // A failed save does not hold up the next one.
    first.reject(new Error("nope"));
    await expect(model).rejects.toThrow("nope");
    await expect(skills).resolves.toBe("skills");
    expect(order).toEqual(["model", "skills"]);
  });

  it("resolves at once when nothing is saving", async () => {
    await expect(awaitPartnerUpdates()).resolves.toBeUndefined();
  });
});

import { afterEach, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { CacheStore } from "../src/cache";
import { FileCache } from "../src/tools/files/cache";

const roots: string[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
async function fixture(bytes = 1024) {
  const root = await mkdtemp(join(tmpdir(), "eneo-cache-test-"));
  roots.push(root);
  const store = new CacheStore(root, 1800000, bytes);
  return { root, store, cache: new FileCache(store) };
}
const bytes = Buffer.from("a,b\n1,2\n");
const etag = '"' + createHash("sha256").update(bytes).digest("hex") + '"';
test("each reuse revalidates and unchanged files transfer no body", async () => {
  const { cache } = await fixture();
  const validators: Array<string | undefined> = [];
  const download = async (options: { etag?: string }) => {
    validators.push(options.etag);
    return options.etag
      ? { bytes: Buffer.alloc(0), contentType: "", name: "", notModified: true }
      : { bytes, contentType: "text/csv", name: "file", etag };
  };
  expect((await cache.fetch("alice/file", download)).bytes).toEqual(bytes);
  expect((await cache.fetch("alice/file", download)).bytes).toEqual(bytes);
  expect(validators).toEqual([undefined, etag]);
  await cache.fetch("bob/file", download);
  expect(validators[2]).toBeUndefined();
});
test("failed authorization never serves stale bytes and invalidates the validator", async () => {
  const { cache } = await fixture();
  await cache.fetch("alice/file", async () => ({
    bytes,
    contentType: "text/csv",
    name: "file",
    etag,
  }));
  await expect(
    cache.fetch("alice/file", async () => {
      throw new Error("403");
    }),
  ).rejects.toThrow("403");
  await cache.fetch("alice/file", async (options) => {
    expect(options.etag).toBeUndefined();
    return { bytes, contentType: "text/csv", name: "file", etag };
  });
});
test("pinned originals and parsed writes share one bounded budget", async () => {
  const { store } = await fixture(10);
  const first = await store.acquire("first", 8, async (dir) => {
    await writeFile(join(dir, "data"), Buffer.alloc(8));
    return "first";
  });
  await expect(store.acquire("second", 8, async () => "second")).rejects.toMatchObject({
    code: "BUSY",
  });
  const secondPin = await store.get<string>("first");
  expect(secondPin?.value).toBe("first");
  await secondPin?.release();
  await first.release();
  const second = await store.acquire("second", 8, async (dir) => {
    await writeFile(join(dir, "data"), Buffer.alloc(8));
    return "second";
  });
  expect(await store.get("first")).toBeUndefined();
  await second.release();
});
test("changed content replaces the cache and incorrect hashes fail closed", async () => {
  const { cache } = await fixture();
  await cache.fetch("file", async () => ({ bytes, contentType: "text/csv", name: "file", etag }));
  await expect(
    cache.fetch("file", async () => ({
      bytes: Buffer.from("changed"),
      contentType: "text/csv",
      name: "file",
      etag,
    })),
  ).rejects.toThrow("validator");
});

test("valid changed content becomes the next validator; legacy responses always download", async () => {
  const { cache } = await fixture();
  const fresh = Buffer.from("changed");
  const freshTag = '"' + createHash("sha256").update(fresh).digest("hex") + '"';
  await cache.fetch("file", async () => ({ bytes, contentType: "text/csv", name: "file", etag }));
  expect(
    (
      await cache.fetch("file", async (options) => {
        expect(options.etag).toBe(etag);
        return { bytes: fresh, contentType: "text/csv", name: "file", etag: freshTag };
      })
    ).bytes,
  ).toEqual(fresh);
  expect(
    (
      await cache.fetch("file", async (options) => {
        expect(options.etag).toBe(freshTag);
        return { bytes: Buffer.alloc(0), contentType: "", name: "", notModified: true };
      })
    ).bytes,
  ).toEqual(fresh);
  for (let i = 0; i < 2; i++)
    await cache.fetch("legacy", async (options) => {
      expect(options.etag).toBeUndefined();
      return { bytes, contentType: "text/csv", name: "file" };
    });
});
test("entry lost after revalidation retries exactly once with an authorized full download", async () => {
  const { root, cache } = await fixture();
  await cache.fetch("file", async () => ({ bytes, contentType: "text/csv", name: "file", etag }));
  let attempts = 0;
  expect(
    (
      await cache.fetch("file", async (options) => {
        attempts++;
        if (options.etag) {
          for (const entry of await readdir(root)) await rm(join(root, entry, "original"));
          return { bytes: Buffer.alloc(0), contentType: "", name: "", notModified: true };
        }
        return { bytes, contentType: "text/csv", name: "file", etag };
      })
    ).bytes,
  ).toEqual(bytes);
  expect(attempts).toBe(2);
});
test.each(["401", "403", "404", "500"])(
  "HTTP %s invalidates cached authorization and never returns stale bytes",
  async (code) => {
    const { cache } = await fixture();
    await cache.fetch("file", async () => ({ bytes, contentType: "text/csv", name: "file", etag }));
    await expect(
      cache.fetch("file", async () => {
        throw new Error(code);
      }),
    ).rejects.toThrow(code);
    await cache.fetch("file", async (options) => {
      expect(options.etag).toBeUndefined();
      return { bytes, contentType: "text/csv", name: "file", etag };
    });
  },
);
test("concurrent cache writes reserve capacity before building and release it on failure", async () => {
  const { store } = await fixture(10);
  let finish!: () => void;
  let entered!: () => void;
  const began = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const pending = store
    .acquire("first", 8, async () => {
      entered();
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      throw new Error("parse failure");
    })
    .catch((error) => error);
  await began;
  await expect(store.acquire("second", 8, async () => "second")).rejects.toMatchObject({
    code: "BUSY",
  });
  finish();
  expect(await pending).toBeInstanceOf(Error);
  const recovered = await store.acquire("second", 8, async () => "second");
  await recovered.release();
});

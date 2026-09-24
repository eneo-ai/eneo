import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, stat, utimes } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { SheetMetadata } from "./ports";

export type CachedFile = { directory: string; sheets: SheetMetadata[] };

/**
 * Parsed workbooks on local disk, so a follow-up question does not re-parse the same file.
 * The cache is never an authorization: every call downloads the file through its signed URL
 * first, and the key is derived from the caller's tenant and user plus the downloaded bytes'
 * hash. An entry therefore only ever serves the principal whose download just succeeded, and a
 * miss (expiry, eviction, restart, another replica) simply parses again.
 */
export class SheetCache {
  private readonly inflight = new Map<string, Promise<CachedFile>>();

  constructor(
    private readonly root: string,
    private readonly ttlMs: number,
    private readonly maxBytes: number,
  ) {}

  static key(parts: { tenantId: string; userId: string; kind: string; sha256: string }): string {
    return createHash("sha256")
      .update(`${parts.tenantId}\n${parts.userId}\n${parts.kind}\n${parts.sha256}`)
      .digest("hex");
  }

  /** Returns the cached entry, or builds it with `build(directory)` exactly once per key. */
  async getOrBuild(
    key: string,
    build: (directory: string) => Promise<SheetMetadata[]>,
  ): Promise<CachedFile> {
    const pending = this.inflight.get(key);
    if (pending) return pending;
    const task = this.lookup(key).then(async (hit) => {
      if (hit) return hit;
      await mkdir(this.root, { recursive: true, mode: 0o700 });
      const staging = join(this.root, `.building-${key}-${crypto.randomUUID()}`);
      await mkdir(staging, { mode: 0o700 });
      try {
        const sheets = await build(staging);
        await Bun.write(join(staging, "meta.json"), JSON.stringify(sheets));
        const directory = join(this.root, key);
        await rm(directory, { recursive: true, force: true });
        await rename(staging, directory);
        await this.evict();
        return { directory, sheets };
      } catch (error) {
        await rm(staging, { recursive: true, force: true });
        throw error;
      }
    });
    this.inflight.set(key, task);
    try {
      return await task;
    } finally {
      this.inflight.delete(key);
    }
  }

  private async lookup(key: string): Promise<CachedFile | undefined> {
    const directory = join(this.root, key);
    try {
      const info = await stat(join(directory, "meta.json"));
      if (Date.now() - info.mtimeMs > this.ttlMs) {
        await rm(directory, { recursive: true, force: true });
        return undefined;
      }
      const sheets = JSON.parse(await readFile(join(directory, "meta.json"), "utf8"));
      const now = new Date();
      await utimes(join(directory, "meta.json"), now, now);
      return { directory, sheets };
    } catch {
      return undefined;
    }
  }

  /** Drops expired entries, then the least recently used ones until the size budget holds. */
  async evict(): Promise<void> {
    let entries: { directory: string; used: number; bytes: number }[] = [];
    try {
      for (const name of await readdir(this.root)) {
        const directory = join(this.root, name);
        if (name.startsWith(".building-")) continue;
        try {
          const used = (await stat(join(directory, "meta.json"))).mtimeMs;
          let bytes = 0;
          for (const file of await readdir(directory))
            bytes += (await stat(join(directory, file))).size;
          entries.push({ directory, used, bytes });
        } catch {
          await rm(directory, { recursive: true, force: true });
        }
      }
    } catch {
      return;
    }
    const now = Date.now();
    for (const entry of entries.filter((e) => now - e.used > this.ttlMs))
      await rm(entry.directory, { recursive: true, force: true });
    entries = entries.filter((e) => now - e.used <= this.ttlMs).sort((a, b) => b.used - a.used);
    let total = 0;
    for (const entry of entries) {
      total += entry.bytes;
      if (total > this.maxBytes) await rm(entry.directory, { recursive: true, force: true });
    }
  }
}

export function defaultCacheRoot(): string {
  return join(tmpdir(), "eneo-tool-runtime-tabular");
}

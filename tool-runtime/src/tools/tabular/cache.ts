import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CacheStore, retain } from "../../cache";
import type { SheetMetadata } from "./ports";

export type CachedFile = { directory: string; sheets: SheetMetadata[] };

export class SheetCache {
  readonly store: CacheStore;
  constructor(
    root: string,
    ttlMs: number,
    maxBytes: number,
    store?: CacheStore,
    private reserveBytes = Math.min(maxBytes, 85 * 1024 * 1024),
  ) {
    this.store = store ?? new CacheStore(root, ttlMs, maxBytes);
  }
  static key(parts: { tenantId: string; userId: string; kind: string; sha256: string }): string {
    return createHash("sha256")
      .update(`${parts.tenantId}\n${parts.userId}\n${parts.kind}\n${parts.sha256}`)
      .digest("hex");
  }
  async getOrBuild(
    key: string,
    build: (directory: string) => Promise<SheetMetadata[]>,
  ): Promise<CachedFile> {
    const lease = await this.store.acquire("sheets:" + key, this.reserveBytes, build);
    retain(lease);
    return { directory: lease.directory, sheets: lease.value };
  }
  evict() {
    return this.store.evict();
  }
  sweepEvery(intervalMs: number) {
    return this.store.sweepEvery(intervalMs);
  }
}

export function defaultCacheRoot(): string {
  return join(tmpdir(), "eneo-tool-runtime-cache");
}

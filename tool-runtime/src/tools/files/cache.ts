import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { CacheStore } from "../../cache";
import { checkCancellation, event } from "../../work";
import type { DownloadedFile, DownloadOptions } from "../tabular/download";

type Metadata = { etag: string; contentType: string; name: string };
export class FileCache {
  // Only bounded opaque identity hashes and validators; never signed URLs/tokens.
  private index = new Map<string, { key: string; etag: string }>();
  constructor(private store: CacheStore) {}
  async fetch(
    identity: string,
    download: (options: DownloadOptions) => Promise<DownloadedFile>,
  ): Promise<DownloadedFile> {
    const prior = this.index.get(identity);
    const lease = prior ? await this.store.get<Metadata>(prior.key) : undefined;
    let result: DownloadedFile;
    try {
      checkCancellation();
      result = await download(lease ? { etag: lease.value.etag } : {});
      if (result.notModified) {
        if (lease) {
          try {
            const bytes = await readFile(join(lease.directory, "original"));
            checkCancellation();
            event("file_cache", { revalidated: true, transferred_bytes: 0 });
            return { ...lease.value, bytes };
          } catch (error) {
            checkCancellation();
            // A missing entry is not authorization to serve another representation.
          }
        }
        result = await download({});
        if (result.notModified) throw new Error("Unexpected unconditional 304");
      }
    } catch (error) {
      // Fail closed for every download error. A future call must reauthorize from scratch.
      if (prior) await this.store.invalidate(prior.key);
      this.index.delete(identity);
      throw error;
    } finally {
      await lease?.release();
    }
    event("file_cache", { revalidated: false, transferred_bytes: result.bytes.length });
    if (prior) await this.store.invalidate(prior.key);
    this.index.delete(identity);
    if (result.etag && /^"[0-9a-f]{64}"$/.test(result.etag)) {
      const digest = createHash("sha256").update(result.bytes).digest("hex");
      if (result.etag !== `"${digest}"`)
        throw new Error("File validator does not match downloaded bytes");
      const key =
        "original:" +
        createHash("sha256")
          .update(identity + "\n" + result.etag)
          .digest("hex");
      try {
        const saved = await this.store.acquire(key, result.bytes.length, async (directory) => {
          await writeFile(join(directory, "original"), result.bytes, { mode: 0o600 });
          return { etag: result.etag!, contentType: result.contentType, name: result.name };
        });
        await saved.release();
        if (this.index.size >= 1024) this.index.delete(this.index.keys().next().value!);
        this.index.set(identity, { key, etag: result.etag });
      } catch (error) {
        checkCancellation();
        // Cache admission is optional; a fully authorized fresh download still works.
        if (!(error instanceof Error && "code" in error && error.code === "BUSY")) throw error;
      }
    }
    return result;
  }
}
let shared: FileCache | undefined;
export function installFileCache(cache: FileCache) {
  shared = cache;
}
export function fileCache() {
  return shared;
}

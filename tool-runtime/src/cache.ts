import { mkdir, mkdtemp, readdir, rm, stat } from "node:fs/promises";
import { join } from "node:path";
import { ToolError } from "./errors";
import { checkCancellation, waitFor, work } from "./work";

type Entry<T = unknown> = {
  directory: string;
  value: T;
  bytes: number;
  pins: number;
  used: number;
};
export type Lease<T> = { directory: string; value: T; release: () => Promise<void> };

/** One budget for originals, parsed sheets, and writes in progress. No shared durable state. */
export class CacheStore {
  private entries = new Map<string, Entry>();
  private pending = new Map<string, Promise<void>>();
  private reserved = 0;
  private tail: Promise<unknown> = Promise.resolve();
  constructor(
    readonly root: string,
    readonly ttlMs: number,
    readonly maxBytes: number,
  ) {}
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const result = this.tail.then(fn, fn);
    this.tail = result.catch(() => {});
    return result;
  }
  private async drop(key: string, entry: Entry) {
    await rm(entry.directory, { recursive: true, force: true });
    this.entries.delete(key);
  }
  private async makeRoom(bytes: number): Promise<void> {
    const now = Date.now();
    for (const [key, entry] of this.entries)
      if (!entry.pins && now - entry.used > this.ttlMs) await this.drop(key, entry);
    let total = this.reserved + [...this.entries.values()].reduce((n, e) => n + e.bytes, 0);
    for (const [key, entry] of [...this.entries].sort((a, b) => a[1].used - b[1].used)) {
      if (total + bytes <= this.maxBytes && (bytes === 0 || this.entries.size < 1024)) break;
      if (!entry.pins) {
        await this.drop(key, entry);
        total -= entry.bytes;
      }
    }
    if (total + bytes > this.maxBytes || (bytes > 0 && this.entries.size >= 1024))
      throw new ToolError(
        "BUSY",
        "The file cache is busy or this file exceeds its budget. Try again or ask the operator to increase the cache budget.",
      );
  }
  private lease<T>(entry: Entry<T>): Lease<T> {
    entry.pins++;
    entry.used = Date.now();
    let released = false;
    return {
      directory: entry.directory,
      value: entry.value,
      release: async () => {
        if (released) return;
        released = true;
        await this.serial(async () => {
          entry.pins--;
          await this.makeRoom(0);
        });
      },
    };
  }
  async get<T>(key: string): Promise<Lease<T> | undefined> {
    return this.serial(async () => {
      const entry = this.entries.get(key);
      if (!entry) return;
      if (Date.now() - entry.used > this.ttlMs) {
        if (!entry.pins) await this.drop(key, entry);
        return;
      }
      return this.lease(entry as Entry<T>);
    });
  }
  async invalidate(key: string): Promise<void> {
    await this.serial(async () => {
      const entry = this.entries.get(key);
      if (entry) {
        entry.used = -Infinity;
        if (!entry.pins) await this.drop(key, entry);
      }
    });
  }
  async acquire<T>(
    key: string,
    reserveBytes: number,
    build: (directory: string) => Promise<T>,
  ): Promise<Lease<T>> {
    for (;;) {
      checkCancellation();
      const hit = await this.get<T>(key);
      if (hit) return hit;
      const pending = this.pending.get(key);
      if (pending) {
        await waitFor(pending);
        continue;
      }
      let finish!: () => void;
      const waiting = new Promise<void>((resolve) => {
        finish = resolve;
      });
      this.pending.set(key, waiting);
      let directory: string | undefined;
      let reserved = false;
      try {
        await this.serial(async () => {
          await this.makeRoom(reserveBytes);
          this.reserved += reserveBytes;
          reserved = true;
        });
        await mkdir(this.root, { recursive: true, mode: 0o700 });
        directory = await mkdtemp(join(this.root, "entry-"));
        checkCancellation();
        const value = await build(directory);
        checkCancellation();
        let bytes = 0;
        for (const file of await readdir(directory))
          bytes += (await stat(join(directory, file))).size;
        if (bytes > reserveBytes)
          throw new ToolError("FILE_TOO_LARGE", "Parsed file exceeded its reserved cache budget.");
        const entry: Entry<T> = { directory, value, bytes, pins: 0, used: Date.now() };
        return await this.serial(async () => {
          // An expired pinned representation may still be in use. Never replace its directory.
          const previous = this.entries.get(key);
          if (previous?.pins)
            throw new ToolError("BUSY", "An expired file is still in use. Retry shortly.");
          if (previous) await this.drop(key, previous);
          this.reserved -= reserveBytes;
          reserved = false;
          this.entries.set(key, entry);
          directory = undefined;
          return this.lease(entry);
        });
      } finally {
        try {
          if (directory) await rm(directory, { recursive: true, force: true });
        } finally {
          if (reserved)
            await this.serial(async () => {
              this.reserved -= reserveBytes;
            });
          this.pending.delete(key);
          finish();
        }
      }
    }
  }
  async evict() {
    await this.serial(() => this.makeRoom(0));
  }
  sweepEvery(intervalMs: number) {
    const timer = setInterval(() => void this.evict().catch(() => {}), intervalMs);
    timer.unref();
    return timer;
  }
}
/** A sheet must remain readable until its tool's last child exits. */
export function retain<T>(lease: Lease<T>): void {
  const current = work.getStore();
  if (current) current.cleanup.push(lease.release);
  else void lease.release(); // Non-server callers/tests own their operation lifetime.
}

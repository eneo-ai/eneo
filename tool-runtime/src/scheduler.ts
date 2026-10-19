import { ToolError } from "./errors";
import { checkCancellation, work } from "./work";

type Waiter = {
  resolve: () => void;
  reject: (error: unknown) => void;
  signal?: AbortSignal;
  abort: () => void;
};
/** Per-process, work-conserving round robin. Groups are opaque and never persisted. */
export class Scheduler {
  private active = 0;
  private queues = new Map<string, Waiter[]>();
  private order: string[] = [];
  private lastGroup?: string;
  constructor(
    private slots: number,
    private maxQueue = 32,
    private maxPerGroup = 8,
  ) {
    if (slots < 1 || maxQueue < 0 || maxPerGroup < 0) throw new Error("Invalid scheduler limits");
  }
  get status() {
    return {
      active: this.active,
      queued: [...this.queues.values()].reduce((n, q) => n + q.length, 0),
    };
  }
  async run<T>(
    task: () => Promise<T>,
    group = work.getStore()?.group ?? "legacy",
    signal = work.getStore()?.signal,
  ): Promise<T> {
    checkCancellation(signal);
    if (this.active < this.slots && !this.order.length) {
      this.active++;
      this.lastGroup = group;
    } else {
      if (
        this.status.queued >= this.maxQueue ||
        (this.queues.get(group)?.length ?? 0) >= this.maxPerGroup
      )
        throw new ToolError("BUSY", "The tool runtime is busy. Try again shortly.");
      await new Promise<void>((resolve, reject) => {
        const waiter: Waiter = {
          resolve,
          reject,
          signal,
          abort: () => {
            const queue = this.queues.get(group);
            const index = queue?.indexOf(waiter) ?? -1;
            if (index < 0) return;
            queue!.splice(index, 1);
            if (!queue!.length) {
              this.queues.delete(group);
              this.order = this.order.filter((key) => key !== group);
            }
            signal?.removeEventListener("abort", waiter.abort);
            reject(signal?.reason ?? new ToolError("CANCELLED", "The operation was cancelled."));
          },
        };
        if (!this.queues.has(group)) {
          this.queues.set(group, []);
          this.order.push(group);
        }
        this.queues.get(group)!.push(waiter);
        signal?.addEventListener("abort", waiter.abort, { once: true });
        if (signal?.aborted) waiter.abort();
      });
    }
    try {
      checkCancellation(signal);
      return await task();
    } finally {
      this.active--;
      this.dispatch();
    }
  }
  private dispatch() {
    while (this.active < this.slots && this.order.length) {
      if (this.order.length > 1 && this.order[0] === this.lastGroup)
        this.order.push(this.order.shift()!);
      const group = this.order.shift()!;
      const queue = this.queues.get(group)!;
      const waiter = queue.shift()!;
      if (queue.length) this.order.push(group);
      else this.queues.delete(group);
      waiter.signal?.removeEventListener("abort", waiter.abort);
      this.active++;
      this.lastGroup = group;
      waiter.resolve();
    }
  }
}

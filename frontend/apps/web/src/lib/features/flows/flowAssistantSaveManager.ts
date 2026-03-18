import { get, writable, type Writable } from "svelte/store";

export type AssistantSaveStatus = "idle" | "pending" | "saving" | "error";

type TimerHandle = ReturnType<typeof setTimeout>;

type AssistantSaveManagerOptions<TAssistant extends object> = {
  loadRemote: (assistantId: string) => Promise<TAssistant | null>;
  saveRemote: (assistantId: string, changes: Record<string, unknown>) => Promise<TAssistant>;
  shouldSaveImmediately: (changes: Record<string, unknown>) => boolean;
  isDisabled: () => boolean;
  getErrorMessage: (error: unknown) => string;
  onValidationError: (assistantId: string, message: string | null) => void;
  onPromptSaved?: (assistantId: string) => void;
  delayMs?: number;
};

export class AssistantSaveManager<TAssistant extends object> {
  readonly status: Writable<AssistantSaveStatus> = writable("idle");

  private readonly cache = new Map<string, TAssistant>();
  private readonly pendingChanges = new Map<string, Record<string, unknown>>();
  private readonly saveTimers = new Map<string, TimerHandle>();
  private readonly inFlight = new Set<string>();
  private readonly savePromises = new Map<string, Promise<void>>();

  constructor(private readonly options: AssistantSaveManagerOptions<TAssistant>) {}

  getStatus(): AssistantSaveStatus {
    return get(this.status);
  }

  primeCache(assistantId: string, assistant: TAssistant): void {
    this.cache.set(assistantId, assistant);
  }

  getCached(assistantId: string): TAssistant | null {
    return this.cache.get(assistantId) ?? null;
  }

  async load(assistantId: string): Promise<TAssistant | null> {
    if (!assistantId) return null;

    if (this.savePromises.has(assistantId)) {
      await this.savePromises.get(assistantId)?.catch(() => {});
    }

    let base = this.cache.get(assistantId) ?? null;
    if (!base) {
      try {
        base = await this.options.loadRemote(assistantId);
      } catch {
        return null;
      }
      if (base) {
        this.cache.set(assistantId, base);
      }
    }

    if (!base) return null;
    return this.mergeWithPending(assistantId, base);
  }

  async save(assistantId: string, changes: Record<string, unknown>): Promise<void> {
    if (!assistantId || this.options.isDisabled()) return;

    const merged = {
      ...(this.pendingChanges.get(assistantId) ?? {}),
      ...changes
    };
    this.pendingChanges.set(assistantId, merged);
    this.options.onValidationError(assistantId, null);

    if (this.getStatus() === "error") {
      this.status.set("pending");
    }

    if (this.options.shouldSaveImmediately(changes)) {
      this.clearTimer(assistantId);
      await this.runSaveNow(assistantId);
      return;
    }

    this.queue(assistantId, this.options.delayMs ?? 500);
  }

  async saveImmediately(assistantId: string, changes: Record<string, unknown>): Promise<void> {
    if (!assistantId || this.options.isDisabled()) return;
    const merged = {
      ...(this.pendingChanges.get(assistantId) ?? {}),
      ...changes
    };
    this.pendingChanges.set(assistantId, merged);
    this.options.onValidationError(assistantId, null);
    this.clearTimer(assistantId);
    await this.runSaveNow(assistantId);
  }

  async flush(): Promise<void> {
    let guard = 0;
    while (guard < 25) {
      guard += 1;
      const ids = new Set<string>([
        ...this.saveTimers.keys(),
        ...this.pendingChanges.keys(),
        ...this.savePromises.keys()
      ]);
      if (ids.size === 0) {
        this.refreshStatus();
        return;
      }
      for (const assistantId of ids) {
        this.clearTimer(assistantId);
      }
      const results = await Promise.allSettled([...ids].map((assistantId) => this.runSaveNow(assistantId)));
      const rejected = results.find((result) => result.status === "rejected");
      if (rejected && rejected.status === "rejected") {
        throw rejected.reason;
      }
    }
    throw new Error("Assistant save flush exceeded retry guard.");
  }

  destroy(): void {
    for (const assistantId of this.saveTimers.keys()) {
      this.clearTimer(assistantId);
    }
  }

  private mergeWithPending(assistantId: string, base: TAssistant): TAssistant {
    const pending = this.pendingChanges.get(assistantId);
    if (!pending) return base;
    return {
      ...base,
      ...pending
    } as TAssistant;
  }

  private clearTimer(assistantId: string): void {
    const existingTimer = this.saveTimers.get(assistantId);
    if (!existingTimer) return;
    clearTimeout(existingTimer);
    this.saveTimers.delete(assistantId);
  }

  private queue(assistantId: string, delayMs: number): void {
    this.clearTimer(assistantId);
    const timer = setTimeout(() => {
      this.saveTimers.delete(assistantId);
      void this.runSaveNow(assistantId).catch(() => {
        // Validation/UI state is updated in runSaveNow.
      });
    }, delayMs);
    this.saveTimers.set(assistantId, timer);
    this.refreshStatus();
  }

  private refreshStatus(): void {
    if (this.inFlight.size > 0) {
      this.status.set("saving");
      return;
    }
    if (this.saveTimers.size > 0 || this.pendingChanges.size > 0) {
      this.status.set("pending");
      return;
    }
    if (this.getStatus() !== "error") {
      this.status.set("idle");
    }
  }

  private async runSaveNow(assistantId: string): Promise<void> {
    if (!assistantId) return;
    if (this.inFlight.has(assistantId)) {
      await this.savePromises.get(assistantId);
      return;
    }

    const merged = this.pendingChanges.get(assistantId);
    if (!merged) return;

    this.pendingChanges.delete(assistantId);
    this.inFlight.add(assistantId);
    this.status.set("saving");

    const savePromise = (async () => {
      try {
        const updated = await this.options.saveRemote(assistantId, merged);
        this.cache.set(assistantId, updated);
        this.options.onValidationError(assistantId, null);
        if ("prompt" in merged) {
          this.options.onPromptSaved?.(assistantId);
        }
      } catch (error) {
        const queued = this.pendingChanges.get(assistantId) ?? {};
        this.pendingChanges.set(assistantId, { ...merged, ...queued });
        this.status.set("error");
        this.options.onValidationError(assistantId, this.options.getErrorMessage(error));
        throw error;
      } finally {
        this.inFlight.delete(assistantId);
        this.savePromises.delete(assistantId);
        this.refreshStatus();
      }
    })();

    this.savePromises.set(assistantId, savePromise);
    await savePromise;

    if (this.pendingChanges.has(assistantId)) {
      this.queue(assistantId, 0);
    }
  }
}

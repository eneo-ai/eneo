import type { EneoUIMessage } from "@/lib/chat/types";
import { deriveActivity, type StepStatus } from "./activity";

/**
 * Client-measured durations for turns streamed in this tab. The backend does
 * not persist step timings, so they exist only for live turns (history shows
 * none): the turn from send to finish, and each step from first seen to
 * finished. An external store (useSyncExternalStore) so observing the stream
 * never sets React state inside an effect.
 */

type Span = { start: number; end: number | null };

type TurnTiming = {
  start: number;
  end: number | null;
  steps: Map<string, Span>;
  /** Completion tokens reported live (transient `data-token-usage`). */
  tokens: number | null;
};

export type TurnDurations = {
  totalMs: number | null;
  stepMs: Record<string, number>;
  tokens: number | null;
  /** When the turn finished (ISO 8601): the timestamp of a live answer. */
  finishedAt: string | null;
};

const FINISHED: ReadonlySet<StepStatus> = new Set(["done", "error", "denied", "stopped"]);

export class ActivityTimings {
  private turns = new Map<string, TurnTiming>();
  private listeners = new Set<() => void>();
  private version = 0;
  private sentAt: number | null = null;
  private pendingTokens: number | null = null;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getVersion = () => this.version;

  private changed() {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }

  /** The user sent a question: the next streamed answer's clock starts now. */
  markSent(now: number = Date.now()) {
    this.sentAt = now;
    this.pendingTokens = null;
  }

  /** Live token usage for the answer being streamed. */
  markTokens(tokens: number) {
    this.pendingTokens = tokens;
  }

  /**
   * Records timings for the answer being streamed (the last message while
   * `streaming`) and closes the turn when streaming stops.
   */
  observe(messages: EneoUIMessage[], streaming: boolean, now: number) {
    const last = messages.at(-1);
    let changed = false;

    if (streaming && last?.role === "assistant") {
      let turn = this.turns.get(last.id);
      if (!turn) {
        turn = { start: this.sentAt ?? now, end: null, steps: new Map(), tokens: null };
        this.turns.set(last.id, turn);
        this.sentAt = null;
        changed = true;
      }
      if (this.pendingTokens !== null && turn.tokens !== this.pendingTokens) {
        turn.tokens = this.pendingTokens;
        changed = true;
      }
      for (const step of deriveActivity(last, { streaming: true }).steps) {
        let span = turn.steps.get(step.key);
        if (!span) {
          span = { start: now, end: null };
          turn.steps.set(step.key, span);
          changed = true;
        }
        if (span.end === null && FINISHED.has(step.status)) {
          span.end = now;
          changed = true;
        }
      }
    }

    if (!streaming) {
      for (const turn of this.turns.values()) {
        if (turn.end !== null) continue;
        turn.end = now;
        for (const span of turn.steps.values()) if (span.end === null) span.end = now;
        if (this.pendingTokens !== null && turn.tokens === null) turn.tokens = this.pendingTokens;
        changed = true;
      }
      this.pendingTokens = null;
    }

    if (changed) this.changed();
  }

  /** Durations for a message; null/empty for turns not streamed in this tab. */
  durations(messageId: string): TurnDurations | null {
    const turn = this.turns.get(messageId);
    if (!turn) return null;
    const stepMs: Record<string, number> = {};
    for (const [key, span] of turn.steps) {
      if (span.end !== null) stepMs[key] = span.end - span.start;
    }
    return {
      totalMs: turn.end === null ? null : turn.end - turn.start,
      stepMs,
      tokens: turn.tokens,
      finishedAt: turn.end === null ? null : new Date(turn.end).toISOString()
    };
  }
}

import type { WidgetClient, WidgetPublicConfig } from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";

/**
 * What the embed page remembers about a visitor, in the iframe's own
 * storage. Browsers partition that storage per top-level site, so this
 * gives continuity across pages of one host site and nothing across sites.
 * Nothing is written until the visitor actually sends a message.
 */
type StoredVisitor = {
  visitor_id: string;
  token: string;
  expires_at: number;
  session_id: string | null;
};

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type VisitorSessionOptions = {
  client: WidgetClient;
  config: Pick<WidgetPublicConfig, "public_id" | "bot_protection" | "token_generation">;
  /** Solve the proof of work and return the ALTCHA payload. */
  solve: () => Promise<string>;
  storage?: StorageLike | null;
  now?: () => number;
  /** Seconds an expired token may still rotate silently (server grace is 60 min). */
  graceSeconds?: number;
};

const EXPIRY_MARGIN_MS = 30_000;

export function storageKey(publicId: string): string {
  return `eneo-widget:${publicId}`;
}

export function isTokenRejected(error: unknown): boolean {
  return error instanceof EneoError && error.status === 401;
}

export function isWidgetUnavailable(error: unknown): boolean {
  return error instanceof EneoError && error.status === 404;
}

export class VisitorSession {
  #client: WidgetClient;
  #config: VisitorSessionOptions["config"];
  #solve: () => Promise<string>;
  #storage: StorageLike | null;
  #now: () => number;
  #grace: number;
  #state: StoredVisitor | null;
  #minting: Promise<string> | null = null;

  constructor(options: VisitorSessionOptions) {
    this.#client = options.client;
    this.#config = options.config;
    this.#solve = options.solve;
    this.#storage = options.storage === undefined ? safeLocalStorage() : options.storage;
    this.#now = options.now ?? (() => Date.now());
    this.#grace = (options.graceSeconds ?? 3600) * 1000;
    this.#state = this.#load();
  }

  /** The token to send right now, or null when nothing has been minted yet. */
  get token(): string | null {
    return this.#state?.token ?? null;
  }

  get visitorId(): string | null {
    return this.#state?.visitor_id ?? null;
  }

  /** Session the visitor was in when the page was last open, for restore. */
  get sessionId(): string | null {
    return this.#state?.session_id ?? null;
  }

  /** True when a still-valid or silently-rotatable token is at hand. */
  get hasIdentity(): boolean {
    const state = this.#state;
    if (!state?.token) return false;
    return state.expires_at + this.#grace > this.#now();
  }

  rememberSession(sessionId: string | null): void {
    if (!this.#state) return;
    this.#state = { ...this.#state, session_id: sessionId };
    this.#save();
  }

  /** Forget the token (the server said it is stale or invalid). */
  invalidate(): void {
    if (!this.#state) return;
    this.#state = { ...this.#state, token: "", expires_at: 0 };
    this.#save();
  }

  /** Forget everything, including the visitor id and remembered session. */
  clear(): void {
    this.#state = null;
    this.#storage?.removeItem(storageKey(this.#config.public_id));
  }

  /**
   * Return a token that is valid for at least a few more seconds, minting or
   * rotating as needed. Concurrent callers share one mint.
   */
  async ensureToken(): Promise<string> {
    const state = this.#state;
    if (state?.token && state.expires_at - EXPIRY_MARGIN_MS > this.#now()) {
      return state.token;
    }
    if (!this.#minting) {
      this.#minting = this.#mint().finally(() => {
        this.#minting = null;
      });
    }
    return this.#minting;
  }

  async #mint(): Promise<string> {
    const previous = this.#state;
    const previousToken =
      previous?.token && previous.expires_at + this.#grace > this.#now() ? previous.token : null;

    if (previousToken) {
      try {
        return this.#store(await this.#client.createVisitorSession({ previousToken }));
      } catch (error) {
        // Stale (config changed) or too old: fall through to a fresh proof of work.
        if (!isTokenRejected(error)) throw error;
      }
    }

    const visitorId = previous?.visitor_id ?? undefined;
    if (this.#config.bot_protection === "none") {
      return this.#store(await this.#client.createVisitorSession({ visitorId }));
    }
    const altcha = await this.#solve();
    return this.#store(await this.#client.createVisitorSession({ altcha, visitorId }));
  }

  #store(session: { token: string; expires_in: number; visitor_id: string }): string {
    this.#state = {
      visitor_id: session.visitor_id,
      token: session.token,
      expires_at: this.#now() + session.expires_in * 1000,
      session_id: this.#state?.session_id ?? null
    };
    this.#save();
    return session.token;
  }

  #load(): StoredVisitor | null {
    try {
      const raw = this.#storage?.getItem(storageKey(this.#config.public_id));
      if (!raw) return null;
      const parsed = JSON.parse(raw) as Partial<StoredVisitor>;
      if (typeof parsed.visitor_id !== "string" || typeof parsed.token !== "string") return null;
      return {
        visitor_id: parsed.visitor_id,
        token: parsed.token,
        expires_at: typeof parsed.expires_at === "number" ? parsed.expires_at : 0,
        session_id: typeof parsed.session_id === "string" ? parsed.session_id : null
      };
    } catch {
      return null;
    }
  }

  #save(): void {
    try {
      if (this.#state) {
        this.#storage?.setItem(storageKey(this.#config.public_id), JSON.stringify(this.#state));
      }
    } catch {
      // Private mode or blocked storage: the session simply does not survive a reload.
    }
  }
}

function safeLocalStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

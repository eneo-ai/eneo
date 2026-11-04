// @ts-check
/**
 * @typedef {import('../../index.js').WidgetClient} WidgetClient
 * @typedef {import('../../index.js').WidgetPublicConfig} WidgetPublicConfig
 * @typedef {{visitor_id: string, visitor_key: string | null, token: string,
 *   expires_at: number, session_id: string | null}} StoredVisitor
 * @typedef {Pick<Storage, "getItem" | "setItem" | "removeItem">} StorageLike
 * @typedef {{client: WidgetClient,
 *   config: Pick<WidgetPublicConfig, "public_id" | "bot_protection" | "token_generation">,
 *   solve: () => Promise<string>, storage?: StorageLike | null, now?: () => number,
 *   graceSeconds?: number, fixedToken?: string | null}} VisitorSessionOptions
 *
 * Identity and conversation continuity inside the iframe. visitor_key proves
 * the server-issued pseudonym. Nothing is stored before the first message.
 * A fixed admin-preview token is never persisted or rotated. graceSeconds is
 * the server's expired-token renewal window (15 minutes by default).
 */
import { EneoError } from "../client/client.js";
import { widgetErrorCode } from "./errors.js";
const EXPIRY_MARGIN_MS = 30_000;
/** @param {string} publicId
 * @returns {string} */
export function storageKey(publicId) {
  return `eneo-widget:${publicId}`;
}
/** @param {unknown} error
 * @returns {boolean} */
export function isTokenRejected(error) {
  return error instanceof EneoError && error.status === 401;
}
/** @param {unknown} error
 * @returns {boolean} */
export function isWidgetUnavailable(error) {
  return error instanceof EneoError && error.status === 404;
}
export class VisitorSession {
  /** @type {WidgetClient} */
  #client;
  /** @type {VisitorSessionOptions["config"]} */
  #config;
  /** @type {() => Promise<string>} */
  #solve;
  /** @type {StorageLike | null} */
  #storage;
  /** @type {() => number} */
  #now;
  /** @type {number} */
  #grace;
  /** @type {StoredVisitor | null} */
  #state;
  /** @type {Promise<string> | null} */
  #minting = null;
  /** @type {string | null} */
  #fixedToken;
  /** @param {VisitorSessionOptions} options */
  constructor(options) {
    this.#client = options.client;
    this.#config = options.config;
    this.#solve = options.solve;
    this.#fixedToken = options.fixedToken ?? null;
    this.#storage =
      this.#fixedToken !== null
        ? null
        : options.storage === undefined
          ? safeLocalStorage()
          : options.storage;
    this.#now = options.now ?? (() => Date.now());
    this.#grace = (options.graceSeconds ?? 900) * 1000;
    this.#state = this.#load();
  }
  /** True for the admin page's live preview; nothing is remembered.
   * @returns {boolean} */
  get isPreview() {
    return this.#fixedToken !== null;
  }
  /** The token to send right now, or null when nothing has been minted yet.
   * @returns {string | null} */
  get token() {
    return this.#fixedToken ?? this.#state?.token ?? null;
  }
  /** @returns {string | null} */
  get visitorId() {
    return this.#state?.visitor_id ?? null;
  }
  /** Session the visitor was in when the page was last open, for restore.
   * @returns {string | null} */
  get sessionId() {
    return this.#state?.session_id ?? null;
  }
  /** True when a still-valid or silently-rotatable token is at hand.
   * @returns {boolean} */
  get hasIdentity() {
    const state = this.#state;
    if (!state?.token) return false;
    return state.expires_at + this.#grace > this.#now();
  }
  /** @param {string | null} sessionId */
  rememberSession(sessionId) {
    if (!this.#state) return;
    this.#state = { ...this.#state, session_id: sessionId };
    this.#save();
  }
  /** Forget the token (the server said it is stale or invalid).  */
  invalidate() {
    if (!this.#state) return;
    this.#state = { ...this.#state, token: "", expires_at: 0 };
    this.#save();
  }
  /** Forget everything, including the visitor id and remembered session.  */
  clear() {
    this.#state = null;
    try {
      this.#storage?.removeItem(storageKey(this.#config.public_id));
    } catch {
      // Storage access can be revoked while the iframe is open. Its in-memory
      // identity is still cleared, just as failed writes leave it usable.
    }
  }
  /**
   * Return a token that is valid for at least a few more seconds, minting or
   * rotating as needed. Concurrent callers share one mint.
   *
   * @returns {Promise<string>} */
  async ensureToken() {
    if (this.#fixedToken !== null) return this.#fixedToken;
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
  /** @returns {Promise<string>} */
  async #mint() {
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
    // The pseudonym is only worth sending with the key the server issued for it.
    const identity =
      previous?.visitor_id && previous.visitor_key
        ? { visitorId: previous.visitor_id, visitorKey: previous.visitor_key }
        : {};
    if (this.#config.bot_protection === "none") {
      try {
        return this.#store(await this.#client.createVisitorSession(identity));
      } catch (error) {
        if (widgetErrorCode(error) !== "challenge_required") throw error;
        // A tenant policy can require ALTCHA while this iframe still has the
        // earlier public config. The server's response is authoritative.
        this.#config = { ...this.#config, bot_protection: "altcha" };
      }
    }
    const altcha = await this.#solve();
    return this.#store(await this.#client.createVisitorSession({ altcha, ...identity }));
  }
  /** @param {{
      token: string;
      expires_in: number;
      visitor_id: string;
      visitor_key: string;
    }} session
   * @returns {string} */
  #store(session) {
    this.#state = {
      visitor_id: session.visitor_id,
      visitor_key: session.visitor_key,
      token: session.token,
      expires_at: this.#now() + session.expires_in * 1000,
      session_id: this.#state?.session_id ?? null
    };
    this.#save();
    return session.token;
  }
  /** @returns {StoredVisitor | null} */
  #load() {
    try {
      const raw = this.#storage?.getItem(storageKey(this.#config.public_id));
      if (!raw) return null;
      const parsed = /** @type {Partial<StoredVisitor>} */ (JSON.parse(raw));
      if (typeof parsed.visitor_id !== "string" || typeof parsed.token !== "string") return null;
      return {
        visitor_id: parsed.visitor_id,
        visitor_key: typeof parsed.visitor_key === "string" ? parsed.visitor_key : null,
        token: parsed.token,
        expires_at: typeof parsed.expires_at === "number" ? parsed.expires_at : 0,
        session_id: typeof parsed.session_id === "string" ? parsed.session_id : null
      };
    } catch {
      return null;
    }
  }
  /** @returns {void} */
  #save() {
    try {
      if (this.#state) {
        this.#storage?.setItem(storageKey(this.#config.public_id), JSON.stringify(this.#state));
      }
    } catch {
      // Private mode or blocked storage: the session simply does not survive a reload.
    }
  }
}
/** @returns {StorageLike | null} */
function safeLocalStorage() {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

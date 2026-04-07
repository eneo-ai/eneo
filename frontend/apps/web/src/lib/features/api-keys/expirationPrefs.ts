const PREFIX = "eneo:api-key-expiry:v1:";
const DISMISS_PREFIX = `${PREFIX}dismiss:`;
const MUTE_PREFIX = `${PREFIX}mute-noncritical:`;
const TTL_MS = 90 * 24 * 60 * 60 * 1000; // 90 days

interface PrefsContext {
  tenantId: string;
  userId: string;
}

function dismissKey(
  ctx: PrefsContext,
  keyId: string,
  expiresAtIso: string,
  level: string
): string {
  return `${DISMISS_PREFIX}${ctx.tenantId}:${ctx.userId}:${keyId}:${expiresAtIso}:${level}`;
}

function muteKey(ctx: PrefsContext): string {
  return `${MUTE_PREFIX}${ctx.tenantId}:${ctx.userId}`;
}

export function isDismissed(
  ctx: PrefsContext,
  keyId: string,
  expiresAtIso: string,
  level: string
): boolean {
  try {
    const raw = localStorage.getItem(dismissKey(ctx, keyId, expiresAtIso, level));
    if (!raw) return false;
    const entry = JSON.parse(raw);
    return entry?.dismissed === true;
  } catch {
    return false;
  }
}

export function dismiss(
  ctx: PrefsContext,
  keyId: string,
  expiresAtIso: string,
  level: string
): void {
  try {
    localStorage.setItem(
      dismissKey(ctx, keyId, expiresAtIso, level),
      JSON.stringify({ dismissed: true, timestamp: Date.now() })
    );
  } catch {
    // localStorage full or unavailable — ignore
  }
}

export function clearForKey(ctx: PrefsContext, keyId: string): void {
  try {
    const prefix = `${DISMISS_PREFIX}${ctx.tenantId}:${ctx.userId}:${keyId}:`;
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k?.startsWith(prefix)) {
        localStorage.removeItem(k);
      }
    }
  } catch {
    // ignore
  }
}

export function isMutedNonCritical(ctx: PrefsContext): boolean {
  try {
    return localStorage.getItem(muteKey(ctx)) === "true";
  } catch {
    return false;
  }
}

export function setMutedNonCritical(ctx: PrefsContext, muted: boolean): void {
  try {
    if (muted) {
      localStorage.setItem(muteKey(ctx), "true");
    } else {
      localStorage.removeItem(muteKey(ctx));
    }
  } catch {
    // ignore
  }
}

/** Purge dismiss entries older than 90 days. Safe to call on any page load. */
export function cleanupExpiredEntries(): void {
  try {
    const now = Date.now();
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (!k?.startsWith(DISMISS_PREFIX)) continue;
      try {
        const raw = localStorage.getItem(k);
        if (!raw) continue;
        const entry = JSON.parse(raw);
        if (typeof entry?.timestamp === "number" && now - entry.timestamp > TTL_MS) {
          localStorage.removeItem(k);
        }
      } catch {
        // Corrupt entry — remove it
        if (k) localStorage.removeItem(k);
      }
    }
  } catch {
    // ignore
  }
}

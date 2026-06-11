import { EncryptJWT, jwtDecrypt } from "jose";
import { z } from "zod";

/**
 * Pure seal/open layer for the encrypted session cookie (JWE, dir + A256GCM).
 * No Next.js imports so it stays unit-testable; cookie I/O lives in session.ts.
 */

export const sessionSchema = z.object({
  mode: z.enum(["oidc", "password"]),
  accessToken: z.string(),
  /** Epoch seconds at which accessToken expires. */
  accessTokenExpiresAt: z.number(),
  refreshToken: z.string().optional(),
  /** Kept for RP-initiated logout (id_token_hint). */
  idToken: z.string().optional(),
  user: z.object({
    email: z.string(),
    name: z.string().optional()
  })
});

export type SessionPayload = z.infer<typeof sessionSchema>;

/** OIDC authorization transaction, parked in a short-lived cookie between
 * /auth/login and /auth/callback. The PKCE verifier must stay confidential,
 * hence the same JWE treatment as the session itself. */
export const txnSchema = z.object({
  verifier: z.string(),
  state: z.string(),
  nonce: z.string(),
  next: z.string().optional()
});

export type TxnPayload = z.infer<typeof txnSchema>;

const keyCache = new Map<string, Uint8Array>();

/** SESSION_SECRET is an arbitrary string; derive a fixed 32-byte key from it. */
async function deriveKey(secret: string): Promise<Uint8Array> {
  const cached = keyCache.get(secret);
  if (cached) return cached;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
  const key = new Uint8Array(digest);
  keyCache.set(secret, key);
  return key;
}

async function seal(claims: Record<string, unknown>, secret: string, maxAgeSeconds: number) {
  const key = await deriveKey(secret);
  return new EncryptJWT(claims)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .setExpirationTime(Math.floor(Date.now() / 1000) + maxAgeSeconds)
    .encrypt(key);
}

async function open<T>(token: string, secret: string, schema: z.ZodType<T>): Promise<T | null> {
  try {
    const key = await deriveKey(secret);
    const { payload } = await jwtDecrypt(token, key);
    const result = schema.safeParse(payload.data);
    return result.success ? result.data : null;
  } catch {
    // Tampered, expired, or not a JWE at all: treated as logged out.
    return null;
  }
}

export function sealSession(session: SessionPayload, secret: string, maxAgeSeconds: number) {
  return seal({ data: session }, secret, maxAgeSeconds);
}

export function openSession(token: string, secret: string) {
  return open(token, secret, sessionSchema);
}

export function sealTxn(txn: TxnPayload, secret: string, maxAgeSeconds: number) {
  return seal({ data: txn }, secret, maxAgeSeconds);
}

export function openTxn(token: string, secret: string) {
  return open(token, secret, txnSchema);
}

/** Refresh when the access token is within this window of expiry. */
export const REFRESH_LEEWAY_SECONDS = 60;

export function needsRefresh(session: SessionPayload, nowEpochSeconds?: number): boolean {
  const now = nowEpochSeconds ?? Math.floor(Date.now() / 1000);
  return session.accessTokenExpiresAt - now <= REFRESH_LEEWAY_SECONDS;
}

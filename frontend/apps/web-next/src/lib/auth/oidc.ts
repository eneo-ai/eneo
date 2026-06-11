import * as client from "openid-client";
import { env } from "@/lib/env";

/**
 * Thin wrapper around openid-client v6 for the generic-OIDC login mode.
 * The app is a confidential client; discovery is configured via OIDC_ISSUER.
 */

export function isOidcEnabled(): boolean {
  return Boolean(env.OIDC_ISSUER);
}

export function redirectUri(): string {
  return `${env.APP_ORIGIN}/auth/callback`;
}

const DISCOVERY_TTL_MS = 60 * 60 * 1000;

let cached: { config: client.Configuration; fetchedAt: number } | null = null;

export async function getOidcConfig(): Promise<client.Configuration> {
  if (!env.OIDC_ISSUER || !env.OIDC_CLIENT_ID || !env.OIDC_CLIENT_SECRET) {
    throw new Error("OIDC is not configured (set OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET)");
  }
  if (cached && Date.now() - cached.fetchedAt < DISCOVERY_TTL_MS) return cached.config;
  const config = await client.discovery(
    new URL(env.OIDC_ISSUER),
    env.OIDC_CLIENT_ID,
    env.OIDC_CLIENT_SECRET
  );
  cached = { config, fetchedAt: Date.now() };
  return config;
}

export interface AuthorizationStart {
  url: string;
  verifier: string;
  state: string;
  nonce: string;
}

export async function startAuthorization(
  config?: client.Configuration
): Promise<AuthorizationStart> {
  const oidcConfig = config ?? (await getOidcConfig());
  const verifier = client.randomPKCECodeVerifier();
  const challenge = await client.calculatePKCECodeChallenge(verifier);
  const state = client.randomState();
  const nonce = client.randomNonce();

  const url = client.buildAuthorizationUrl(oidcConfig, {
    redirect_uri: redirectUri(),
    scope: env.OIDC_SCOPES,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
    nonce
  });

  return { url: url.href, verifier, state, nonce };
}

export interface OidcTokens {
  accessToken: string;
  accessTokenExpiresAt: number;
  refreshToken?: string;
  idToken?: string;
  claims: { email?: string; name?: string };
}

function toTokens(
  response: client.TokenEndpointResponse & client.TokenEndpointResponseHelpers
): OidcTokens {
  const claims = response.claims();
  return {
    accessToken: response.access_token,
    accessTokenExpiresAt: accessTokenExpiry(response.expires_in),
    refreshToken: response.refresh_token,
    idToken: response.id_token,
    claims: {
      email: typeof claims?.email === "string" ? claims.email : undefined,
      name: typeof claims?.name === "string" ? claims.name : undefined
    }
  };
}

/** Epoch seconds the access token expires at; defaults to 5 minutes when the
 * IdP omits expires_in (the proxy then refreshes on that cadence). */
export function accessTokenExpiry(expiresIn: number | undefined, nowEpochSeconds?: number) {
  const now = nowEpochSeconds ?? Math.floor(Date.now() / 1000);
  return now + (expiresIn ?? 300);
}

export async function completeAuthorization(
  currentUrl: URL,
  txn: { verifier: string; state: string; nonce: string }
): Promise<OidcTokens> {
  const config = await getOidcConfig();
  const response = await client.authorizationCodeGrant(config, currentUrl, {
    pkceCodeVerifier: txn.verifier,
    expectedState: txn.state,
    expectedNonce: txn.nonce
  });
  return toTokens(response);
}

export async function refreshTokens(refreshToken: string): Promise<OidcTokens> {
  const config = await getOidcConfig();
  const response = await client.refreshTokenGrant(config, refreshToken);
  return toTokens(response);
}

/** RP-initiated logout URL, or null when the IdP has no end_session_endpoint. */
export async function buildLogoutUrl(idToken: string | undefined): Promise<string | null> {
  const config = await getOidcConfig();
  if (!config.serverMetadata().end_session_endpoint) return null;
  const url = client.buildEndSessionUrl(config, {
    post_logout_redirect_uri: `${env.APP_ORIGIN}/login`,
    ...(idToken ? { id_token_hint: idToken } : {})
  });
  return url.href;
}

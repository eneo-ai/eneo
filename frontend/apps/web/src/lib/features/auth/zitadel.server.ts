/**
 * Login via Zitadel. This is the preferred login method. It requires a Zitadel instance to be configured.
 */
import { dev } from "$app/environment";
import { env } from "$env/dynamic/private";
import type { Cookies } from "@sveltejs/kit";
import { createCodePair, encodeState, setFrontendAuthCookie } from "./auth.server";
import { LoginError } from "./LoginError";
import { getRequestEvent } from "$app/server";

/** Name of the cookie we use to store the code verifier */
const ZitadelVerifierCookie = "zitadel-verifier" as const;
/** Scopes that always will be requested from Zitadel */
const basicScopes = ["openid", "email", "urn:zitadel:iam:org:project:id:zitadel:aud"] as const;

/**
 * Get the configured public origin for OIDC redirect URIs.
 *
 * SECURITY: Uses explicit PUBLIC_ORIGIN configuration instead of
 * event.url.origin to prevent redirect_uri mismatches behind reverse proxies.
 *
 * @returns The configured public origin (e.g., "https://eneo.sundsvall.se")
 * @throws Error if PUBLIC_ORIGIN is not configured
 */
function getPublicOrigin(): string {
  if (!env.PUBLIC_ORIGIN) {
    throw new Error(
      '[OIDC] PUBLIC_ORIGIN environment variable is required for OIDC authentication. ' +
      'Set it to the externally-reachable URL for this application. ' +
      'Example: PUBLIC_ORIGIN=https://eneo.sundsvall.se'
    );
  }

  // Validate format (basic check)
  if (!env.PUBLIC_ORIGIN.startsWith('https://')) {
    throw new Error(
      '[OIDC] PUBLIC_ORIGIN must be an https:// URL for security. ' +
      `Got: ${env.PUBLIC_ORIGIN}`
    );
  }

  // Remove trailing slash if present
  return env.PUBLIC_ORIGIN.replace(/\/$/, '');
}

/** Function to get all scopes based on a origin (e.g. when using a subdomain) */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function getScopeByOrigin(origin?: string) {
  // Basic scope
  const scopes: string[] = [...basicScopes];
  // const { fetch } = getRequestEvent();

  // try {
  //   // Lookup org id via origin
  //   if (origin && env.INTRIC_SYS_API_KEY) {
  //     const client = createClient({
  //       baseUrl: env.INTRIC_BACKEND_URL!,
  //       apiKey: env.INTRIC_SYS_API_KEY,
  //       fetch
  //     });
  //     const tenant = await client.fetch("/api/v1/sysadmin/tenants/", {
  //       method: "get",
  //       params: {
  //         query: { domain: origin }
  //       }
  //     });
  //     if (tenant.items.length === 1 && tenant.items[0].zitadel_org_id) {
  //       scopes.push(`urn:zitadel:iam:org:id:${tenant.items[0].zitadel_org_id}`);
  //     }
  //   }
  // } catch {
  //   // In this case we just don't add the additional scope
  // }

  return scopes;
}

/** Function to directly construct scope if we already have an orgId */
function getScopeByOrgId(orgId: string) {
  return [...basicScopes, `urn:zitadel:iam:org:id:${orgId}`];
}

export async function getZitadelLink(
  event: {
    url: URL;
    cookies: Cookies;
  },
  options?: {
    registerUser?: boolean;
    orgId?: string;
  }
) {
  // Only generate an url if the environment is correctly set
  // This should have been taken care of by the login/+page.server.ts already
  if (!env.ZITADEL_PROJECT_CLIENT_ID || !env.ZITADEL_INSTANCE_URL) {
    return undefined;
  }

  const { registerUser = false, orgId = null } = options ?? {};
  const {
    url: { origin, searchParams }
  } = event;

  const scopes = orgId ? getScopeByOrgId(orgId) : await getScopeByOrigin(origin);
  const { codeVerifier, codeChallenge } = await createCodePair();

  event.cookies.set(ZitadelVerifierCookie, codeVerifier, {
    path: "/",
    httpOnly: true,
    expires: new Date(Date.now() + 1 * 60 * 60 * 1000), // Expires in one hour
    secure: !dev,
    sameSite: "lax"
  });

  const authParams = new URLSearchParams({
    scope: scopes.join(" "),
    client_id: env.ZITADEL_PROJECT_CLIENT_ID,
    response_type: "code",
    redirect_uri: `${getPublicOrigin()}/login/callback`,
    state: encodeState({ loginMethod: "zitadel", next: searchParams.get("next") }),
    code_challenge: codeChallenge,
    code_challenge_method: "S256"
  });

  if (registerUser) {
    authParams.append("prompt", "create");
  }

  return env.ZITADEL_INSTANCE_URL + "/oauth/v2/authorize?" + authParams.toString();
}

export async function loginWithZitadel(code: string): Promise<boolean> {
  // Onlytry to login if the environment is correctly set
  // This should have been taken care of by the login/callback/+page.server.ts already
  if (!env.ZITADEL_PROJECT_CLIENT_ID || !env.ZITADEL_INSTANCE_URL) {
    throw new LoginError("zitadel", "NO_CONFIG");
  }

  const event = getRequestEvent();

  const code_verifier = event.cookies.get(ZitadelVerifierCookie);

  if (!code_verifier) {
    throw new LoginError("zitadel", "NO_VERIFIER");
  }

  const searchParams = new URLSearchParams({
    client_id: env.ZITADEL_PROJECT_CLIENT_ID,
    code,
    code_verifier,
    grant_type: "authorization_code",
    redirect_uri: `${getPublicOrigin()}/login/callback`
  });

  const tokenUrl = env.ZITADEL_INSTANCE_URL + "/oauth/v2/token?" + searchParams.toString();

  const response = await event.fetch(tokenUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    }
  });

  if (!response.ok) {
    throw new LoginError("zitadel", "NO_TOKEN");
  }

  try {
    const tokens = (await response.json()) as { id_token: string; access_token: string };
    await setFrontendAuthCookie(tokens);
    event.cookies.delete(ZitadelVerifierCookie, { path: "/" });
    return true;
  } catch (error) {
    const message =
      typeof error === "object" && error && "message" in error ? (error.message as string) : "";
    throw new LoginError("zitadel", "DECODE_ERROR", message);
  }
}

export function clearZitadelCookie(cookies: Cookies) {
  cookies.delete(ZitadelVerifierCookie, { path: "/" });
}

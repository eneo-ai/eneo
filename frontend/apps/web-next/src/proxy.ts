import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { refreshTokens } from "@/lib/auth/oidc";
import {
  needsRefresh,
  openSession,
  sealSession,
  type SessionPayload
} from "@/lib/auth/session-codec";
import { OIDC_SESSION_MAX_AGE_SECONDS, SESSION_COOKIE } from "@/lib/auth/session";
import {
  EMBED_LOCALE_HEADER,
  EMBED_SCHEME_HEADER,
  embedPolicy,
  parseEmbedPath,
  type EmbedPolicy
} from "@/features/widget/server/embed-policy";

/**
 * Optimistic auth gating + the sliding OIDC refresh. Real authorization is
 * the backend's job; this only keeps logged-out users away from app pages and
 * keeps the access token in the session cookie fresh (proxy is the one place
 * that can always write cookies, unlike RSC rendering).
 */

const PUBLIC_PREFIXES = [
  "/login",
  "/auth",
  "/logout",
  "/healthz",
  "/deactivated",
  "/password-change",
  "/activate",
  // The invitation notice (links to /login; Zitadel registration is not ported).
  "/invite",
  // Gates the session itself so its login redirect carries its own headers.
  "/module-login",
  "/integrations/callback",
  // The embeddable widget: the chat a visitor of another site sees, the
  // loader's script, stylesheet and settings, and the visitor API behind
  // them (src/app/api/v1/widgets, src/app/api/v1/icons). None of it has a
  // session; a visitor's token is its own bearer header.
  "/embed",
  "/en/embed",
  "/widget",
  "/api/v1/widgets",
  "/api/v1/icons"
];

function createNonce(): string {
  const uuid = crypto.randomUUID();
  return typeof btoa === "function" ? btoa(uuid) : Buffer.from(uuid).toString("base64");
}

export function buildContentSecurityPolicy(
  nonce: string,
  nodeEnv: string | undefined = process.env.NODE_ENV,
  // Origins the chat may frame besides blob: documents: the content origin
  // interactive tool views (MCP Apps) are served from.
  frameOrigins: readonly string[] = env.MCP_APP_CONTENT_ORIGIN ? [env.MCP_APP_CONTENT_ORIGIN] : []
): string {
  const isDevelopment = nodeEnv === "development";
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDevelopment ? " 'unsafe-eval'" : ""}`,
    // The dev tools (Next.js dev overlay, TanStack Query devtools) inject
    // <style> elements without the nonce, and a nonce in the list makes
    // browsers ignore 'unsafe-inline', so development leaves the nonce out.
    isDevelopment ? "style-src 'self' 'unsafe-inline'" : `style-src 'self' 'nonce-${nonce}'`,
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    "media-src 'self' blob: data:",
    // Signed file previews are fetched through our API proxy and framed from
    // an in-memory blob; the widget editor frames its own embed page; tool
    // views come from their own origin. Other frame origins remain blocked.
    ["frame-src 'self' blob:", ...frameOrigins].join(" "),
    `connect-src 'self'${isDevelopment ? " ws: http: https:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    // Blob documents inherit this policy. Same-origin ancestors let the PDF
    // viewer render, while cross-origin sites still cannot frame the app.
    "frame-ancestors 'self'",
    "script-src-attr 'none'",
    ...(isDevelopment ? [] : ["upgrade-insecure-requests"])
  ];
  return directives.join("; ");
}

/** `csp` with these directives set (replacing any with the same name). */
function withDirectives(csp: string, directives: Record<string, string>): string {
  const kept = csp.split("; ").filter((directive) => !(directive.split(" ")[0]! in directives));
  return [...kept, ...Object.entries(directives).map(([name, value]) => `${name} ${value}`)].join(
    "; "
  );
}

/**
 * The policy of an embed page: the app's own, framed only where the widget's
 * configuration allows (the loader's host sites; never on the stand-alone
 * page), showing no image from outside Eneo and connecting to nothing but
 * itself: answer Markdown can carry any image URL, and an injected one would
 * ship the visitor's question to a third party (the visitor API is proxied
 * under this origin). The proof-of-work widget (ALTCHA) spawns its workers
 * from blob: URLs. The page never frames anything itself.
 */
export function buildEmbedContentSecurityPolicy(
  nonce: string,
  policy: Pick<EmbedPolicy, "frameAncestors">,
  nodeEnv: string | undefined = process.env.NODE_ENV
): string {
  return withDirectives(buildContentSecurityPolicy(nonce, nodeEnv, []), {
    "frame-ancestors": policy.frameAncestors,
    "img-src": "'self' blob: data:",
    "frame-src": "'none'",
    "worker-src": "'self' blob:",
    "base-uri": "'none'"
  });
}

function createSecurityRequestHeaders(request: NextRequest, nonce: string, csp: string): Headers {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  // The page being rendered, for server-side redirects that should bring the
  // user back here afterwards (see lib/api/server.ts). Set here so a client
  // cannot supply its own value.
  requestHeaders.set("x-eneo-path", request.nextUrl.pathname + request.nextUrl.search);
  return requestHeaders;
}

function withContentSecurityPolicy<T extends NextResponse>(response: T, csp: string): T {
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

// Phones get the same app as desktop (the shell turns the SideNav into a
// drawer); there is no user-agent redirect to /dashboard any more.
function authenticatedResponse(requestHeaders: Headers, csp: string) {
  return withContentSecurityPolicy(
    NextResponse.next({ request: { headers: requestHeaders } }),
    csp
  );
}

function isPublic(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

function loginRedirect(request: NextRequest, csp: string) {
  const url = new URL("/login", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") url.searchParams.set("next", next);
  const response = NextResponse.redirect(url);
  response.cookies.delete(SESSION_COOKIE);
  return withContentSecurityPolicy(response, csp);
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const nonce = createNonce();
  // An embed page is framed by other sites and starts in the language and
  // colour scheme of its widget, so its policy is decided here from the
  // widget's configuration, before the page renders.
  const embed = parseEmbedPath(pathname);
  const embedHeaders = embed ? await embedPolicy(embed, request.nextUrl.searchParams) : null;
  const csp = embedHeaders
    ? buildEmbedContentSecurityPolicy(nonce, embedHeaders)
    : buildContentSecurityPolicy(nonce);
  const securityRequestHeaders = createSecurityRequestHeaders(request, nonce, csp);
  if (embedHeaders) {
    securityRequestHeaders.set(EMBED_LOCALE_HEADER, embedHeaders.locale);
    securityRequestHeaders.set(EMBED_SCHEME_HEADER, embedHeaders.scheme);
  }

  // SameSite cookies also accompany requests from sibling subdomains. Bind
  // mutations to the configured app origin, never a forwarded Host header.
  if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
    if (request.headers.get("origin") !== new URL(env.APP_ORIGIN).origin) {
      return withContentSecurityPolicy(
        NextResponse.json({ message: "Untrusted request origin" }, { status: 403 }),
        csp
      );
    }
  }

  const apiRequest = pathname.startsWith("/api/");
  const publicPage = isPublic(pathname);
  // These public pages can consume an existing session during RSC rendering.
  const sessionPage = ["/deactivated", "/activate", "/module-login", "/password-change"].some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
  const pass = () => authenticatedResponse(securityRequestHeaders, csp);
  const rejected = () => {
    if (!apiRequest && !publicPage) return loginRedirect(request, csp);
    const response = apiRequest
      ? withContentSecurityPolicy(
          NextResponse.json({ message: "Unauthenticated" }, { status: 401 }),
          csp
        )
      : pass();
    response.cookies.delete(SESSION_COOKIE);
    return response;
  };

  // skipTrailingSlashRedirect (needed for /api/eneo) disables the built-in
  // normalization, so page routes strip the trailing slash here instead.
  // Plain URL on purpose: NextURL's pathname setter re-applies the original
  // trailing slash, which would redirect to itself.
  if (!apiRequest && pathname.length > 1 && pathname.endsWith("/")) {
    const url = new URL(request.url);
    url.pathname = pathname.replace(/\/+$/, "");
    return withContentSecurityPolicy(NextResponse.redirect(url, 308), csp);
  }

  if (publicPage && !sessionPage) return pass();

  const raw = request.cookies.get(SESSION_COOKIE)?.value;
  if (!raw) return apiRequest || publicPage ? pass() : rejected();

  const session = await openSession(raw, env.SESSION_SECRET);
  if (!session) return rejected();

  if (session.mode === "oidc" && session.refreshToken && needsRefresh(session)) {
    let refreshed: SessionPayload;
    try {
      const tokens = await refreshTokens(session.refreshToken);
      refreshed = {
        ...session,
        accessToken: tokens.accessToken,
        accessTokenExpiresAt: tokens.accessTokenExpiresAt,
        refreshToken: tokens.refreshToken ?? session.refreshToken,
        idToken: tokens.idToken ?? session.idToken
      };
    } catch {
      // Refresh token rejected or IdP unreachable: the session is over.
      return rejected();
    }

    const sealed = await sealSession(refreshed, env.SESSION_SECRET, OIDC_SESSION_MAX_AGE_SECONDS);

    // Rewrite the request cookie so RSCs in THIS request already see the
    // refreshed session, and set the response cookie to persist it.
    const rewrittenCookies = request.cookies
      .getAll()
      .map((cookie) =>
        cookie.name === SESSION_COOKIE
          ? `${SESSION_COOKIE}=${sealed}`
          : `${cookie.name}=${cookie.value}`
      )
      .join("; ");
    securityRequestHeaders.set("cookie", rewrittenCookies);

    const response = authenticatedResponse(securityRequestHeaders, csp);
    response.cookies.set(SESSION_COOKIE, sealed, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: OIDC_SESSION_MAX_AGE_SECONDS
    });
    return response;
  }

  // Password mode has no refresh (until RB-3): an expired token means login.
  if (session.accessTokenExpiresAt <= Math.floor(Date.now() / 1000)) {
    return rejected();
  }

  return authenticatedResponse(securityRequestHeaders, csp);
}

export const config = {
  // Everything except Next internals and static assets (anything with a file
  // extension); public paths are filtered in code above.
  matcher: ["/api/:path*", "/((?!_next/|.*\\..*).*)"]
};

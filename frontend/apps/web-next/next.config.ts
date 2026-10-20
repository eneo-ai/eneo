import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/lib/i18n/request.ts");

/** Security response headers applied to every route. The nonce-based CSP is
 * request-specific and lives in src/proxy.ts instead of static next.config
 * headers.
 */
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" }
];

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker runner stage (see Dockerfile).
  output: "standalone",

  // Backend routes are slash-sensitive and reached through /api/eneo/…/; the
  // built-in redirect would strip the trailing slash before the proxy route
  // handler runs. src/proxy.ts keeps the strip-slash redirect for page routes.
  skipTrailingSlashRedirect: true,

  experimental: {
    // Every request that src/proxy.ts matches (all of /api/eneo) has its body
    // cloned for the proxy, and Next silently cuts the clone at this size: a
    // bigger upload reaches the backend without its file part and fails with
    // 422 "Field required" (the default is 10 MB). Keep it above the largest
    // upload the backend's storage policy allows.
    proxyClientMaxBodySize: "1gb"
  },

  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  }
};

export default withNextIntl(nextConfig);

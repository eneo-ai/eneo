import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/lib/i18n/request.ts");

const nextConfig: NextConfig = {
  // Backend routes are slash-sensitive and reached through /api/eneo/…/; the
  // built-in redirect would strip the trailing slash before the proxy route
  // handler runs. src/proxy.ts keeps the strip-slash redirect for page routes.
  skipTrailingSlashRedirect: true
};

export default withNextIntl(nextConfig);

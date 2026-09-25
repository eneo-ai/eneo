import type { NextConfig } from "next";
import nextra from "nextra";
import localizeMdxLinks from "./scripts/localize-mdx-links.mjs";

const withNextra = nextra({
  // Disable staticImage so mdx-components.js handles images with basePath
  staticImage: false,
  mdxOptions: { remarkPlugins: [localizeMdxLinks] },
});

const nextConfig: NextConfig = withNextra({
  output: "export",
  // Version builds run sequentially and use one prerender worker.
  experimental: {
    cpus: 1,
    // <html lang> follows the URL language, so no root layout exists and the
    // site-wide 404 must render its own document.
    globalNotFound: true,
  },
  basePath: process.env.PAGES_BASE_PATH,
  env: {
    NEXT_PUBLIC_BASE_PATH: process.env.PAGES_BASE_PATH || "",
  },
});

export default nextConfig;

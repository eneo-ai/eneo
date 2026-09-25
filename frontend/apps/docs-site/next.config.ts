import type { NextConfig } from "next";
import nextra from "nextra";

const withNextra = nextra({
  // Disable staticImage so mdx-components.js handles images with basePath
  staticImage: false,
});

const nextConfig: NextConfig = withNextra({
  output: "export",
  // Version builds run sequentially and use one prerender worker.
  experimental: { cpus: 1 },
  basePath: process.env.PAGES_BASE_PATH,
  env: {
    NEXT_PUBLIC_BASE_PATH: process.env.PAGES_BASE_PATH || "",
  },
});

export default nextConfig;

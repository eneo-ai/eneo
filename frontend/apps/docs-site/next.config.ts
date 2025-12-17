import type { NextConfig } from "next";
import nextra from 'nextra';

const withNextra = nextra({
  // ... Add Nextra-specific options here
})

const nextConfig: NextConfig = withNextra({
  output: 'standalone',
});

export default nextConfig;

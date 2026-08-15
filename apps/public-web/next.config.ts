import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Every club site is served by this one deployment; the club is resolved
  // from the Host header at request time. See src/lib/site.ts.
  poweredByHeader: false,
  experimental: { optimizePackageImports: [] },
};

export default config;

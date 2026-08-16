import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Every club site is served by this one deployment; the club is resolved
  // from the Host header at request time. See src/lib/site.ts.
  poweredByHeader: false,
  // A self-contained server bundle: the production image copies `.next/standalone`
  // and needs no `node_modules` of its own, which takes the image from about a
  // gigabyte to under two hundred megabytes.
  output: "standalone",
  experimental: { optimizePackageImports: [] },
};

export default config;

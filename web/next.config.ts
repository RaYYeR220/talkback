import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  agentRules: false,
  devIndicators: false,
};

export default nextConfig;

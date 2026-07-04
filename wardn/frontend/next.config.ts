import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.1.101"],
  devIndicators: false,
  output: "standalone",
};

export default nextConfig;

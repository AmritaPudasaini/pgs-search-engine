import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone (server.js + only the node_modules it needs) so the
  // Docker image (ui/Dockerfile) ships without a full node_modules. `npm run dev`
  // is unaffected.
  output: "standalone",
};

export default nextConfig;

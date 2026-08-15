import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Behind Traefik the browser connects to admin.footbola.localhost:80,
    // so HMR must be told where to reach back to.
    hmr: { clientPort: 80, host: "admin.footbola.localhost" },
    allowedHosts: ["admin.footbola.localhost", "localhost"],
  },
  build: { sourcemap: true },
});

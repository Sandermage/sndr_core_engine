import { defineConfig } from "vite";
import path from "node:path";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
    },
    build: {
      // xterm (Terminal) is lazy-loaded into its own chunk.
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          // Pin the React runtime into a stable vendor chunk so it stays cached
          // across app-code redeploys. The regex matches react/react-dom/scheduler
          // only — lucide-react (per-icon, tree-shaken) is intentionally excluded.
          manualChunks(id) {
            if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) {
              return "react-vendor";
            }
            return undefined;
          },
        },
      },
    },
  };
});

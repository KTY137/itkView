import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

declare const process: {
  env: Record<string, string | undefined>;
};

// Explicit IPv4: the backend binds 127.0.0.1, so proxy there directly. Using
// "localhost" here is a trap on Windows/modern Node, where it can resolve to
// ::1 first and miss an IPv4-only backend.
const backendUrl = process.env.ITKFLOW_BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // Pin the dev port. `strictPort` makes Vite fail loudly if 5173 is taken
    // instead of silently drifting to 5174/5175 and stranding the user on a
    // stale or dead tab (the recurring "can't log in" symptom).
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": backendUrl,
      "/health": backendUrl,
    },
  },
});

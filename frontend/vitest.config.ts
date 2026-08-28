import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Most frontend tests exercise the shared authoring implementation. Keep
    // that regression path explicit while production builds default to View.
    env: { VITE_ITKFLOW_PRODUCT_VARIANT: "flow" },
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    pool: "threads",
    maxWorkers: 1,
    fileParallelism: false,
    // jsdom + userEvent interaction tests finish in ~1.5 s idle but have been
    // measured past 5 s on a busy machine (several agents or a sync sweep in
    // the background), which turned correct tests red. Raise the ceiling so a
    // red result means broken, not busy; a genuinely hanging test still fails.
    testTimeout: 20_000,
    clearMocks: true,
    restoreMocks: true,
  },
});

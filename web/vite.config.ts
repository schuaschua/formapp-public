import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { PREVIEW_SECURITY_HEADERS } from "./security-headers.ts";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    // The api serves these from /app/static; source maps would publish the source.
    sourcemap: false,
  },
  preview: {
    // E2E_WEB_PORT/E2E_API_PORT let parallel worktrees run the Playwright stack side by side
    // (scripts/check.sh gives each worktree its own ports).
    port: Number(process.env.E2E_WEB_PORT ?? 4173),
    strictPort: true,
    headers: PREVIEW_SECURITY_HEADERS,
    // Story 1.10: the local Playwright stack's api (playwright.config.ts's second `webServer`),
    // so `apiFetch`'s same-origin /api calls reach it with no CORS or app config change.
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${process.env.E2E_API_PORT ?? "8000"}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/tests/**", "src/**/*.test.{ts,tsx}"],
      reporter: ["text", "text-summary"],
      // coding-style.md rule 25: never lower this; add tests instead.
      thresholds: { lines: 60 },
    },
  },
});

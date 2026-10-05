import { defineConfig, devices } from "@playwright/test";

// Story 1.4: axe and the 200% zoom check in Chromium against the production build (`vite preview`).
// Story 1.10 adds the local api + PostgreSQL stack (journey 1, never Azure, P1-018): a second
// `webServer` entry starts `api` in test mode against the database `scripts/check.sh e2e` (or a
// by-hand run of `api/scripts/e2e_bootstrap.py`) laid out; `vite.config.ts`'s `preview.proxy`
// forwards `/api` to it. E2E_WEB_PORT/E2E_API_PORT give each worktree its own ports.
const webPort = process.env.E2E_WEB_PORT ?? "4173";
const apiPort = process.env.E2E_API_PORT ?? "8000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: `http://localhost:${webPort}`,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
      },
    },
  ],
  webServer: [
    {
      command: "npm run build && npm run preview",
      url: `http://localhost:${webPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `uv run --no-sync uvicorn adapters.rest.app:create_app --factory --host 127.0.0.1 --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/healthz`,
      cwd: "../api",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        FORMAPP_DEPLOYMENT: "local",
        FORMAPP_TEST_MODE: "true",
        DATABASE_HOST: process.env.PGHOST ?? "127.0.0.1",
        DATABASE_PORT: process.env.PGPORT ?? "5432",
        // The database `api/scripts/e2e_bootstrap.py` lays out (scripts/check.sh's e2e section, or
        // one run by hand); DATABASE_USER/PASSWORD must match the values that script's own
        // `tests.support.create_database` creates the login role with exactly (a plain TS/Python
        // constant, so kept in sync by hand -- there is no shared source for the two languages).
        DATABASE_NAME: process.env.FORMAPP_E2E_DB ?? "formapp_e2e",
        DATABASE_USER: "formapp_api_test",
        DATABASE_PASSWORD: "synthetic-api-password",
        DATABASE_SSLMODE: "disable",
        DB_MIGRATION_ROLE: "formapp_migrator",
        TURN_TOKEN_SIGNING_KEY: "synthetic-signing-key-synthetic-signing-key-",
      },
    },
  ],
});

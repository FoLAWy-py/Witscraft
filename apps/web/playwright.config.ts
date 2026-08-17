import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3100/witscraft",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"]
  },
  webServer: {
    command: "NEXT_PUBLIC_BASE_PATH=/witscraft NEXT_PUBLIC_API_BASE_URL=/witscraft npm run start -- --port 3100",
    url: "http://127.0.0.1:3100/witscraft",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000
  }
});

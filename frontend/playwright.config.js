import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.CODEMAFIA_E2E_WEB_URL || 'http://127.0.0.1:5173';
const apiURL = process.env.CODEMAFIA_E2E_API_URL || 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: process.env.CODEMAFIA_E2E_WEB_URL ? undefined : {
    command: 'npm run dev',
    url: baseURL,
    env: { VITE_API_BASE_URL: apiURL },
    reuseExistingServer: true,
    timeout: 30_000,
  },
});

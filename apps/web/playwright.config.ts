import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests',
  timeout: 90000,
  expect: { timeout: 20000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: '../../.local/playwright-results.json' }]],
  use: { baseURL: process.env.TEST_WEB_URL || 'http://localhost:5288', viewport: { width: 1600, height: 1100 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})

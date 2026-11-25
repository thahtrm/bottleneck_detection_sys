import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, defineConfig } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function resolveChromiumExecutable() {
  const envExe = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (envExe && fs.existsSync(envExe)) {
    return envExe;
  }

  try {
    const defaultExe = chromium.executablePath();
    if (defaultExe && fs.existsSync(defaultExe)) {
      return defaultExe;
    }
  } catch {
    // Ignore and inspect ms-playwright cache + system paths below.
  }

  const cacheRoot = path.join(os.homedir(), '.cache', 'ms-playwright');
  if (fs.existsSync(cacheRoot)) {
    const entries = fs.readdirSync(cacheRoot);
    const parseRev = (name) => {
      const m = name.match(/-(\d+)$/);
      return m ? Number(m[1]) : 0;
    };

    const chromiumDirs = entries
      .filter((d) => d.startsWith('chromium-'))
      .sort((a, b) => parseRev(b) - parseRev(a));
    for (const dir of chromiumDirs) {
      const candidate = path.join(cacheRoot, dir, 'chrome-linux64', 'chrome');
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }

    const headlessDirs = entries
      .filter((d) => d.startsWith('chromium_headless_shell-'))
      .sort((a, b) => parseRev(b) - parseRev(a));
    for (const dir of headlessDirs) {
      const candidate = path.join(
        cacheRoot,
        dir,
        'chrome-headless-shell-linux64',
        'chrome-headless-shell',
      );
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }
  }

  const systemFallbacks = [
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/opt/microsoft/msedge/msedge',
  ];
  for (const candidate of systemFallbacks) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

const isDryRun = process.env.E2E_DRY_RUN === '1';
const baseUrl = process.env.E2E_BASE_URL ? process.env.E2E_BASE_URL.replace(/\/$/, '') : undefined;
const executablePath = isDryRun ? undefined : resolveChromiumExecutable();

export default defineConfig({
  testDir: path.join(__dirname, 'specs'),
  testMatch: '**/*.spec.mjs',
  workers: 1,
  fullyParallel: false,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  retries: 0,
  reporter: [['list']],
  outputDir: path.join(__dirname, 'test-results'),
  use: {
    ...(baseUrl ? { baseURL: baseUrl } : {}),
    headless: process.env.E2E_HEADED !== '1',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: {
      ...(executablePath ? { executablePath } : {}),
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    },
  },
});

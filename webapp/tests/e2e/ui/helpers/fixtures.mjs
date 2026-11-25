import { test as base, expect } from '@playwright/test';
import { startIsolatedServer } from './server.mjs';
import { ensureRoleCredentials, loginViaApi, loginViaForm } from './auth.mjs';

function isExternalFontNoise(text) {
  return (
    process.env.E2E_OFFLINE === '1' &&
    (text.includes('fonts.googleapis.com') || text.includes('fonts.gstatic.com'))
  );
}

function isExpectedAuthProbe401(msg) {
  const text = msg.text();
  const locUrl = msg.location()?.url || '';
  return text.includes('401 (Unauthorized)') && locUrl.includes('/api/auth/me');
}

export const test = base.extend({
  appServer: async ({}, use) => {
    const server = await startIsolatedServer({ richNetwork: true, seed: true });
    try {
      await use(server);
    } finally {
      await server.stop();
    }
  },

  errorCollector: async ({ page, appServer }, use) => {
    const errors = [];
    const allowedConsoleStatuses = new Set();

    const onPageError = (err) => {
      errors.push(`pageerror: ${err.message || String(err)}`);
    };
    const onConsole = (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (isExternalFontNoise(text) || isExpectedAuthProbe401(msg)) {
          return;
        }
        const matchedAllowed = [...allowedConsoleStatuses].some((code) =>
          text.includes(`status of ${code}`),
        );
        if (!matchedAllowed) {
          errors.push(`console.error: ${text}`);
        }
      }
    };
    const onResponse = (res) => {
      const url = res.url();
      if (url.startsWith(appServer.baseUrl) && res.status() >= 500) {
        errors.push(`http ${res.status()}: ${res.request().method()} ${url}`);
      }
    };

    page.on('pageerror', onPageError);
    page.on('console', onConsole);
    page.on('response', onResponse);

    const assertNoErrors = () => {
      expect(errors, `Unexpected browser/server errors:\n${errors.join('\n')}`).toEqual([]);
    };
    const allowStatus = (code) => {
      allowedConsoleStatuses.add(String(code));
    };

    await use({ errors, assertNoErrors, allowStatus });

    page.off('pageerror', onPageError);
    page.off('console', onConsole);
    page.off('response', onResponse);
    assertNoErrors();
  },

  loginAs: async ({ page, appServer }, use) => {
    const helper = async (role, { method = 'api' } = {}) => {
      const creds = await ensureRoleCredentials(appServer.baseUrl, role);
      if (method === 'form') {
        return loginViaForm(page, appServer.baseUrl, creds);
      }
      return loginViaApi(page, appServer.baseUrl, creds);
    };
    await use(helper);
  },
});

export async function gotoView(page, baseUrl, view, params = {}) {
  const navMap = {
    board: 'Bảng',
    list: 'Danh sách',
    graph: 'Đồ thị',
    chat: 'Chat',
    reports: 'Báo cáo',
    users: 'Người dùng',
    'project-settings': 'Cài đặt dự án',
    settings: 'Cài đặt',
  };

  const hasExtraParams = Object.keys(params).length > 0;
  if (!hasExtraParams && navMap[view]) {
    const navBtn = page
      .locator('nav[aria-label="Điều hướng chính"] button.erw-nav-item')
      .filter({ hasText: navMap[view] });
    if ((await navBtn.count()) > 0 && (await navBtn.first().isVisible())) {
      await navBtn.first().click();
      return;
    }
  }

  const qs = new URLSearchParams({ view, ...params });
  await page.goto(`${baseUrl}/?${qs.toString()}`, { waitUntil: 'domcontentloaded' });
}

export { expect };

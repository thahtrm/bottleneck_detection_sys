import { test, expect, gotoView } from '../helpers/fixtures.mjs';

test.describe('E2E-M1 UI Harness Smoke', () => {
  test('@tier1 @F03 smoke: unauthenticated user sees Login page and signs in as admin', async ({
    page,
    appServer,
    errorCollector,
    loginAs,
  }) => {
    await page.goto(appServer.baseUrl, { waitUntil: 'domcontentloaded' });

    await expect(page.getByLabel('Địa chỉ Email')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Đăng nhập' })).toBeVisible();

    await loginAs('admin', { method: 'form' });

    const nav = page.locator('nav[aria-label="Điều hướng chính"]');
    await expect(nav).toBeVisible();
    for (const label of ['Bảng', 'Danh sách', 'Đồ thị', 'Người dùng', 'Cài đặt']) {
      await expect(nav.getByRole('button', { name: label })).toBeVisible();
    }

    errorCollector.assertNoErrors();
  });

  test('@tier1 @F03 @F30 smoke: authenticated PM checks RBAC nav, views list/graph, and opens issue panel', async ({
    page,
    appServer,
    errorCollector,
    loginAs,
  }) => {
    await loginAs('pm', { method: 'api' });

    const nav = page.locator('nav[aria-label="Điều hướng chính"]');
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Bảng' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Danh sách' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Đồ thị' })).toBeVisible();
    await expect(nav.getByRole('button', { name: 'Người dùng' })).toHaveCount(0);

    await gotoView(page, appServer.baseUrl, 'list');
    const demoIssueText = page.getByText(/DEMO-\d+/).first();
    await expect(demoIssueText).toBeVisible({ timeout: 15_000 });
    const issueKey = (await demoIssueText.textContent())?.match(/DEMO-\d+/)?.[0] ?? 'DEMO-';
    await demoIssueText.click();

    await expect(page).toHaveURL(/issue=DEMO-\d+/);
    const aside = page.locator('aside');
    await expect(aside).toBeVisible({ timeout: 10_000 });
    await expect(aside.getByText(issueKey).first()).toBeVisible({ timeout: 10_000 });
    await expect(aside.getByText(/Tổng quan & Rủi ro/i)).toBeVisible({ timeout: 10_000 });

    await gotoView(page, appServer.baseUrl, 'graph');
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 15_000 });

    errorCollector.assertNoErrors();
  });
});

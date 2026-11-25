import { test, expect } from '../helpers/fixtures.mjs';

test.describe('E2E Jira views', () => {
  test('@tier1 PM can open Jira board, backlog, and issues from the nav', async ({
    page,
    errorCollector,
    loginAs,
  }) => {
    await loginAs('pm', { method: 'api' });

    const nav = page.locator('nav[aria-label="Điều hướng chính"]');
    await expect(nav.getByText('Workspace / Jira', { exact: true })).toBeVisible();
    for (const label of ['Jira board', 'Backlog', 'Issues', 'Bảng']) {
      await expect(nav.getByRole('button', { name: label, exact: true })).toBeVisible();
    }

    const main = page.locator('main');

    await nav.getByRole('button', { name: 'Jira board', exact: true }).click();
    await expect(page).toHaveURL(/[?&]view=jira-board(?:&|$)/);
    const boardReady = main.locator('.erw-jira-board, .erw-settings-error').or(
      main.locator('.erw-settings-body').filter({ hasText: /Select a project|no workflow columns/ }),
    );
    await expect(boardReady.first()).toBeVisible();

    await nav.getByRole('button', { name: 'Backlog', exact: true }).click();
    await expect(page).toHaveURL(/[?&]view=backlog(?:&|$)/);

    await nav.getByRole('button', { name: 'Issues', exact: true }).click();
    await expect(page).toHaveURL(/[?&]view=navigator(?:&|$)/);

    await expect(nav.getByRole('button', { name: 'Bảng', exact: true })).toBeVisible();
    errorCollector.assertNoErrors();
  });
});

import { expect, test } from '@playwright/test';

const apiURL = process.env.CODEMAFIA_E2E_API_URL || 'http://127.0.0.1:8000';
const editorURL = process.env.CODEMAFIA_E2E_EDITOR_URL || 'http://127.0.0.1:1234';

test('repair, civilian regression, attributable sabotage, recovery and rematch', async ({ browser, request }) => {
  test.setTimeout(240_000);
  for (const url of [`${apiURL}/health`, `${editorURL}/health`]) {
    expect((await request.get(url, { failOnStatusCode: false })).ok(), `Start the live stack: ${url}`).toBe(true);
  }
  const contexts = [];
  try {
    const pages = [];
    for (let index = 0; index < 4; index += 1) {
      const context = await browser.newContext();
      contexts.push(context);
      const page = await context.newPage();
      pages.push(page);
      await page.goto('/');
      await expect(page.getByLabel('Your player name')).toBeEnabled();
      await page.getByLabel('Your player name').fill(`Repair player ${index + 1}`);
    }
    await pages[0].getByRole('button', { name: /Create a room/ }).click();
    const code = (await pages[0].locator('[aria-label^="Room code "]').textContent()).trim();
    for (const page of pages.slice(1)) {
      await page.getByLabel('Room code').fill(code);
      await page.getByRole('button', { name: 'Join', exact: true }).click();
    }
    for (const page of pages) {
      await expect(page.getByRole('button', { name: 'I’m ready' })).toBeEnabled();
      await page.getByRole('button', { name: 'I’m ready' }).click();
    }
    await expect(pages[0].getByRole('button', { name: /Start match/ })).toBeEnabled();
    await pages[0].getByRole('button', { name: /Start match/ }).click();
    for (const page of pages) {
      await page.getByRole('button', { name: /Object-Oriented Programming/ }).click();
    }
    for (const page of pages) {
      await expect(page.getByRole('heading', { name: 'Repair the Counter' })).toBeVisible({ timeout: 30_000 });
    }
    const roles = await Promise.all(pages.map((p) => p.getByText('Impostor', { exact: true }).isVisible()));
    expect(roles.filter(Boolean)).toHaveLength(1);
    const impostor = pages[roles.indexOf(true)];
    const civilian = pages[roles.indexOf(false)];
    for (const page of [civilian, impostor]) {
      await page.getByRole('button', { name: 'Use accessible text editor' }).click();
      await expect(page.getByRole('textbox', { name: 'Shared Python code' })).toBeEditable();
    }
    const editor = (page) => page.getByRole('textbox', { name: 'Shared Python code' });
    await expect.poll(() => editor(civilian).inputValue()).toContain('class Counter');
    const starter = await editor(civilian).inputValue();
    const repaired = starter.replace('self.count -= 2', 'self.count -= 1')
      .replace('        pass', '        self.count = 0\n        self.history.append("reset")');

    async function editAndCheck(page, source, passes) {
      const revision = page.locator('p').filter({ hasText: 'Current revision:' }).locator('code');
      const before = await revision.textContent();
      await editor(page).fill(source);
      await expect(revision).not.toHaveText(before);
      // Automatic runs may already be queued; never assume the button is enabled.
      const run = page.getByRole('button', { name: 'Run official tests', exact: true });
      if (await run.isVisible() && await run.isEnabled()) await run.click();
      await expect(page.getByText(passes
        ? 'All required server checks passed. This result is a candidate until a player finalizes the current revision.'
        : 'The saved revision did not pass every required server check.', { exact: true }))
        .toBeVisible({ timeout: 45_000 });
    }

    await editAndCheck(civilian, repaired, true);
    await editAndCheck(civilian, repaired.replace('self.count -= 1', 'self.count -= 2'), false);
    await expect(impostor.getByText(/3 verification credits left/)).toBeVisible();
    await expect(impostor.getByText('Pending', { exact: true })).toBeVisible();
    await editAndCheck(civilian, repaired, true);
    await expect.poll(() => editor(impostor).inputValue()).toBe(repaired);
    await editAndCheck(impostor, repaired.replace('self.count -= 1', 'self.count -= 2'), false);
    await expect(impostor.getByText('Verified · defend until deadline', { exact: true })).toBeVisible();
    await expect(impostor.getByText(/2 verification credits left/)).toBeVisible();
    await expect(civilian.getByRole('heading', { name: 'Repair the Counter' })).toBeVisible();

    // Mid-round reconnect must retain private progress and the spent credit.
    await impostor.reload();
    await expect(impostor.getByText(/2 verification credits left/)).toBeVisible({ timeout: 30_000 });
    await expect(impostor.getByText('Verified · defend until deadline', { exact: true })).toBeVisible();
    await editAndCheck(civilian, repaired, true);
    await expect(impostor.getByText('Pending', { exact: true })).toBeVisible();
    await civilian.getByRole('button', { name: 'Finalize verified solution' }).click();
    for (const page of pages) {
      await expect(page.getByRole('heading', { name: 'The civilians win.' })).toBeVisible();
    }
    for (const page of pages) await page.getByRole('button', { name: /Request rematch/ }).click();
    for (const page of pages) await expect(page.getByRole('button', { name: 'I’m ready' })).toBeVisible();
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

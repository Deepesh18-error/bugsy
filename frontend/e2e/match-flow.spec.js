import { expect, test } from '@playwright/test';

const apiURL = process.env.CODEMAFIA_E2E_API_URL || 'http://127.0.0.1:8000';
const editorURL = process.env.CODEMAFIA_E2E_EDITOR_URL || 'http://127.0.0.1:1234';
const names = ['Ada', 'Bela', 'Cora', 'Davi'];

test.beforeAll(async ({ request }) => {
  for (const [name, url] of [['FastAPI and Redis', `${apiURL}/health`], ['editor sync', `${editorURL}/health`]]) {
    const response = await request.get(url, { failOnStatusCode: false }).catch(() => null);
    expect(response?.ok(), `Start ${name} before running the live browser suite (${url}).`).toBe(true);
  }
});

test('four independent players reach a server-verified match result', async ({ browser }) => {
  const contexts = [];
  try {
    const pages = [];
    for (let index = 0; index < names.length; index += 1) {
      const context = await browser.newContext();
      contexts.push(context);
      const page = await context.newPage();
      pages.push(page);
      await page.goto('/');
      await expect(page.getByLabel('Your player name')).toBeEnabled();
    }

    await test.step('create, join, ready, and start', async () => {
      await pages[0].getByLabel('Your player name').fill(names[0]);
      await pages[0].getByRole('button', { name: /Create a room/ }).click();
      const roomCode = (await pages[0].locator('[aria-label^="Room code "]').textContent()).trim();
      expect(roomCode).toMatch(/^[A-Z2-9]{8}$/);

      for (let index = 1; index < pages.length; index += 1) {
        await pages[index].getByLabel('Your player name').fill(names[index]);
        await pages[index].getByLabel('Room code').fill(roomCode);
        await pages[index].getByRole('button', { name: 'Join', exact: true }).click();
        await expect(pages[index].locator('[aria-label^="Room code "]')).toHaveText(roomCode);
      }

      for (const page of pages) {
        await expect(page.getByRole('button', { name: 'I’m ready' })).toBeEnabled();
        await page.getByRole('button', { name: 'I’m ready' }).click();
        await expect(page.getByRole('button', { name: /You’re ready/ })).toBeVisible();
      }
      await expect(pages[0].getByRole('button', { name: /Start match/ })).toBeEnabled();
      await pages[0].getByRole('button', { name: /Start match/ }).click();
      await Promise.all(pages.map((page) => expect(page.getByRole('heading', { name: 'Pick a category' })).toBeVisible()));
    });

    await test.step('vote for the authored challenge and receive private roles', async () => {
      for (const page of pages) {
        await page.getByRole('button', { name: /Object-Oriented Programming/ }).click();
      }
      await Promise.all(pages.map((page) => expect(page.getByRole('heading', { name: 'Repair the Counter' })).toBeVisible({ timeout: 30_000 })));
      const impostorFlags = await Promise.all(pages.map((page) => page.getByText('Impostor', { exact: true }).isVisible()));
      expect(impostorFlags.filter(Boolean)).toHaveLength(1);
      const impostorName = names[impostorFlags.indexOf(true)];

      await test.step('concurrent edits converge and the official runner reports on the saved revision', async () => {
        const revision = pages[0].locator('p').filter({ hasText: 'Current revision:' }).locator('code');
        await expect(revision).not.toHaveText('Waiting for server…');
        const originalRevision = await revision.textContent();
        for (const page of pages.slice(0, 2)) {
          await page.getByRole('button', { name: 'Use accessible text editor' }).click();
          await expect(page.getByRole('textbox', { name: 'Shared Python code' })).toBeEditable();
        }
        const first = pages[0].getByRole('textbox', { name: 'Shared Python code' });
        const second = pages[1].getByRole('textbox', { name: 'Shared Python code' });
        await expect.poll(() => first.inputValue()).toContain('class Counter');
        await expect.poll(() => second.inputValue()).toContain('class Counter');
        const initialSource = await first.inputValue();
        await Promise.all([
          first.fill(`${initialSource}\n# e2e edit from Ada\n`),
          second.fill(`${initialSource}\n# e2e edit from Bela\n`),
        ]);
        for (const editor of [first, second]) {
          await expect.poll(() => editor.inputValue()).toContain('# e2e edit from Ada');
          await expect.poll(() => editor.inputValue()).toContain('# e2e edit from Bela');
        }
        await expect.poll(() => first.inputValue()).toBe(await second.inputValue());
        await expect(revision).not.toHaveText(originalRevision);
        const officialButton = pages[0].getByRole('button', { name: 'Run official tests' });
        if (await officialButton.isEnabled()) await officialButton.click();
        await expect(pages[0].getByRole('button', { name: 'Result received' })).toBeVisible({ timeout: 45_000 });
        await expect(pages[0].getByText('The saved revision did not pass every required server check.')).toBeVisible();
      });

      await test.step('meet, vote privately, and resolve one winner', async () => {
        await pages[0].getByRole('button', { name: 'Call emergency meeting' }).click();
        await Promise.all(pages.map((page) => expect(page.getByRole('heading', { name: 'What happened?' })).toBeVisible()));
        await Promise.all(pages.map((page) => expect(page.getByRole('heading', { name: 'Select a player' })).toBeVisible({ timeout: 45_000 })));
        for (let index = 0; index < pages.length; index += 1) {
          if (names[index] === impostorName) {
            await pages[index].getByRole('button', { name: 'Skip this vote' }).click();
          } else {
            await pages[index].getByRole('button', { name: new RegExp(impostorName) }).click();
          }
          await pages[index].getByRole('button', { name: /Submit vote/ }).click();
        }
        for (const page of pages) {
          await expect(page.getByRole('heading', { name: /The vote is in\.|The civilians win\./ })).toBeVisible();
          const continueButton = page.getByRole('button', { name: 'Continue', exact: true });
          if (await continueButton.isVisible()) await continueButton.click();
          await expect(page.getByRole('heading', { name: 'The civilians win.' })).toBeVisible();
        }
      });
    });
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

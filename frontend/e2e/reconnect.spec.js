import { expect, test } from '@playwright/test';

const apiURL = process.env.CODEMAFIA_E2E_API_URL || 'http://127.0.0.1:8000';

test.beforeAll(async ({ request }) => {
  const response = await request.get(`${apiURL}/health`, { failOnStatusCode: false }).catch(() => null);
  expect(response?.ok(), 'Start FastAPI and Redis before running the live browser suite.').toBe(true);
});

test('refresh and tab reopening restore the same player, readiness, and chat', async ({ browser }) => {
  const hostContext = await browser.newContext();
  const guestContext = await browser.newContext();
  try {
    const host = await hostContext.newPage();
    let guest = await guestContext.newPage();
    await Promise.all([host.goto('/'), guest.goto('/')]);
    await Promise.all([
      expect(host.getByLabel('Your player name')).toBeEnabled(),
      expect(guest.getByLabel('Your player name')).toBeEnabled(),
    ]);

    await host.getByLabel('Your player name').fill('Host Ada');
    await host.getByRole('button', { name: /Create a room/ }).click();
    const roomCode = (await host.locator('[aria-label^="Room code "]').textContent()).trim();
    await guest.getByLabel('Your player name').fill('Guest Bela');
    await guest.getByLabel('Room code').fill(roomCode);
    await guest.getByRole('button', { name: 'Join', exact: true }).click();
    await expect(guest.locator('[aria-label^="Room code "]')).toHaveText(roomCode);
    await guest.getByRole('button', { name: 'I’m ready' }).click();
    await expect(guest.getByRole('button', { name: /You’re ready/ })).toBeVisible();

    await guest.reload();
    await expect(guest.locator('[aria-label^="Room code "]')).toHaveText(roomCode);
    await expect(guest.getByRole('button', { name: /You’re ready/ })).toBeVisible();

    await guest.close();
    const message = `Rejoin check ${Date.now()}`;
    await host.getByRole('textbox', { name: 'Write a chat message' }).fill(message);
    await host.getByRole('button', { name: 'Send message' }).click();
    await expect(host.getByText(message, { exact: true })).toBeVisible();

    guest = await guestContext.newPage();
    await guest.goto('/');
    await expect(guest.locator('[aria-label^="Room code "]')).toHaveText(roomCode);
    await expect(guest.getByRole('button', { name: /You’re ready/ })).toBeVisible();
    await expect(guest.getByText(message, { exact: true })).toHaveCount(1);
    await expect(guest.getByText('Guest Bela', { exact: true })).toBeVisible();
  } finally {
    await Promise.all([hostContext.close(), guestContext.close()]);
  }
});

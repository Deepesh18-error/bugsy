import { expect, test } from '@playwright/test';

const apiURL = process.env.CODEMAFIA_E2E_API_URL || 'http://127.0.0.1:8000';
const editorURL = process.env.CODEMAFIA_E2E_EDITOR_URL || 'http://127.0.0.1:1234';

test.beforeAll(async ({ request }) => {
  for (const url of [`${apiURL}/health`, `${editorURL}/health`]) {
    const response = await request.get(url, { failOnStatusCode: false }).catch(() => null);
    expect(response?.ok(), `Start the live service at ${url} before running this test.`).toBe(true);
  }
});

test('room snapshots and role events reveal only the recipient’s private data', async ({ browser }) => {
  const contexts = [];
  try {
    const pages = [];
    const received = [];
    for (let index = 0; index < 4; index += 1) {
      const context = await browser.newContext();
      contexts.push(context);
      const page = await context.newPage();
      const messages = [];
      page.on('websocket', (socket) => socket.on('framereceived', (frame) => {
        try { messages.push(JSON.parse(String(frame.payload))); } catch { /* Yjs frames are binary. */ }
      }));
      pages.push(page);
      received.push(messages);
      await page.goto('/');
      await expect(page.getByLabel('Your player name')).toBeEnabled();
    }

    await pages[0].getByLabel('Your player name').fill('Ada');
    await pages[0].getByRole('button', { name: /Create a room/ }).click();
    const code = (await pages[0].locator('[aria-label^="Room code "]').textContent()).trim();
    for (let index = 1; index < 4; index += 1) {
      await pages[index].getByLabel('Your player name').fill(`Player ${index}`);
      await pages[index].getByLabel('Room code').fill(code);
      await pages[index].getByRole('button', { name: 'Join', exact: true }).click();
    }
    for (const page of pages) {
      await page.getByRole('button', { name: 'I’m ready' }).click();
      await expect(page.getByRole('button', { name: /You’re ready/ })).toBeVisible();
    }
    await pages[0].getByRole('button', { name: /Start match/ }).click();
    for (const page of pages) {
      await page.getByRole('button', { name: /Object-Oriented Programming/ }).click();
    }
    await Promise.all(pages.map((page) => expect(page.getByRole('heading', { name: 'Repair the Counter' })).toBeVisible({ timeout: 30_000 })));

    const latestRooms = [];
    for (const messages of received) {
      await expect.poll(() => messages.filter((message) => message.type === 'snapshot')
        .at(-1)?.room?.own_role).toMatch(/^(civilian|impostor)$/);
      const snapshots = messages.filter((message) => message.type === 'snapshot');
      const latest = snapshots.at(-1).room;
      latestRooms.push(latest);
      for (const snapshot of snapshots) {
        expect(snapshot.room.players.every((player) => !('role' in player))).toBe(true);
        expect(JSON.stringify(snapshot)).not.toContain('reference_solution');
        expect(JSON.stringify(snapshot)).not.toContain('credential_hash');
      }
      for (const event of messages.filter((message) => message.type === 'event'
        && message.name === 'PlayerRoleAssigned')) {
        expect(event.payload.role).toBe(latest.own_role);
      }
    }
    expect(latestRooms.filter((room) => room.own_role === 'impostor')).toHaveLength(1);
    for (const room of latestRooms) {
      if (room.own_role === 'civilian') expect(room.own_objectives).toEqual([]);
      else expect(room.own_objectives.length).toBeGreaterThan(0);
    }
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

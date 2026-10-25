import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

async function expectAccessible(page) {
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(result.violations, JSON.stringify(result.violations, null, 2)).toEqual([]);
}

async function expectNoHorizontalOverflow(page) {
  const widths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth, viewport: window.innerWidth,
  }));
  expect(widths.page).toBeLessThanOrEqual(widths.viewport + 1);
}

test('welcome and preview lobby support keyboard focus and automated accessibility checks', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Explore the local match preview' })).toBeEnabled();
  await expectAccessible(page);

  await page.getByLabel('Your player name').focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: /Create a room/ })).toBeFocused();

  await page.getByRole('button', { name: 'Explore the local match preview' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toBeFocused();
  await expectAccessible(page);
});

test('the preview match screens keep labelled controls and readable contrast', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Explore the local match preview' }).click();
  await page.getByRole('button', { name: 'I’m ready' }).click();
  await page.getByRole('button', { name: /Start match/ }).click();
  await expect(page.getByRole('heading', { name: 'Pick a category' })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('button', { name: /Object-Oriented Programming/ }).click();
  await page.getByRole('button', { name: /Reveal my role/ }).click();
  await expect(page.getByRole('heading', { level: 1 })).toBeFocused();
  await expectAccessible(page);

  await page.getByRole('button', { name: /Continue to coding round/ }).click();
  await expect(page.getByRole('heading', { level: 1 })).toBeFocused();
  await expectAccessible(page);

  await page.getByRole('button', { name: /Call emergency meeting/ }).click();
  await expectAccessible(page);
  await page.getByRole('button', { name: /End discussion & open vote/ }).click();
  await expectAccessible(page);

  await page.getByRole('button', { name: 'Skip this vote' }).click();
  await page.getByRole('button', { name: /Submit vote/ }).click();
  await expectAccessible(page);
  await page.getByRole('button', { name: /Continue to results/ }).click();
  await expectAccessible(page);
});

test('a narrow viewport keeps the game actions within the page', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Explore the local match preview' }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'I’m ready' }).click();
  await page.getByRole('button', { name: /Start match/ }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: /Object-Oriented Programming/ }).click();
  await page.getByRole('button', { name: /Reveal my role/ }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: /Continue to coding round/ }).click();
  await expectNoHorizontalOverflow(page);
  await expectAccessible(page);
  await page.getByRole('button', { name: /Call emergency meeting/ }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: /End discussion & open vote/ }).click();
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Skip this vote' }).click();
  await page.getByRole('button', { name: /Submit vote/ }).click();
  await page.getByRole('button', { name: /Continue to results/ }).click();
  await expectNoHorizontalOverflow(page);
});

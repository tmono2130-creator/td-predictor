// Read-only smoke check of the actual served data, with no intercepted responses.
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const { chromium } = createRequire(import.meta.url)('playwright');
const base = process.env.BASE_URL;
if (!base || !/^https:\/\/td-predictor\.vercel\.app$|^http:\/\/localhost:\d+$/.test(base)) {
  throw new Error('An explicit approved production or localhost URL is required');
}
const root = new URL('../public/data/', import.meta.url);
const manifest = JSON.parse(fs.readFileSync(new URL('manifest.json', root), 'utf8'));
const browser = await chromium.launch({ headless: true,
  ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.url().startsWith(base + '/data/') && response.status() !== 200) {
      errors.push(`Data response ${response.status()}`);
    }
  });
  const response = await page.goto(base);
  assert.equal(response.status(), 200, 'Website must be accessible; protection/login is not a passing smoke check');
  await page.getByText('Leading TD estimates', { exact: true }).waitFor();
  for (const [season, entry] of Object.entries(manifest.seasons)) {
    await page.getByLabel('Season', { exact: true }).selectOption(season);
    for (const [week, files] of Object.entries(entry.weeks)) {
      await page.getByLabel('Week', { exact: true }).selectOption(week);
      await page.getByText(`Week ${week} · ${season}`, { exact: true }).waitFor();
      const board = JSON.parse(fs.readFileSync(new URL(files.board, root), 'utf8'));
      await page.getByRole('navigation').getByRole('button', { name: 'Player Rankings', exact: true }).click();
      await page.getByLabel('Rows', { exact: true }).selectOption('1000');
      assert.equal(await page.locator('table tbody tr').count(), board.rows.length);
      for (const section of ['Parlay Builder', 'Market Check', 'Game Breakdown', 'Dashboard']) {
        await page.getByRole('navigation').getByRole('button', { name: section, exact: true }).click();
        if (section === 'Game Breakdown') {
          await page.getByLabel('Game', { exact: true }).waitFor();
          for (const label of ['Offensive Identity', 'Defensive Vulnerabilities', 'TD Recommendations']) {
            await page.getByRole('group', { name: 'Game Breakdown sections' }).getByRole('button', { name: label, exact: true }).click();
            if (files.matchup_intelligence) {
              await page.getByRole('region', { name: label === 'TD Recommendations' ? 'Matchup-Based TD Recommendations' : label, exact: true }).waitFor();
              assert.equal(await page.getByRole('alert').count(), 0, 'Published intelligence must validate and render');
            } else {
              await page.getByText('Matchup Intelligence has not been published for this snapshot.', { exact: false }).waitFor();
            }
          }
          await page.getByRole('group', { name: 'Game Breakdown sections' }).getByRole('button', { name: 'TD Breakdown', exact: true }).click();
        }
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
      }
    }
  }
  assert.deepEqual(errors, []);
  console.log('PASS actual published weeks, player coverage, mobile navigation and runtime errors');
} finally {
  await browser.close();
}

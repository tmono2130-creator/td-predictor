// Read-only smoke check of the actual served data, with no intercepted responses.
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import { gameFreshness } from '../lib/game-projection.ts';
const { chromium } = createRequire(import.meta.url)('playwright');
const base = process.env.BASE_URL;
const contentHealthOnly = process.env.CONTENT_HEALTH_ONLY === 'true';
if (contentHealthOnly && !/^http:\/\/localhost:\d+$/.test(base || '')) {
  throw new Error('Source-only content health mode is restricted to localhost; production release verification stays strict');
}
if (!base || !/^https:\/\/onopm\.space$|^http:\/\/localhost:\d+$/.test(base)) {
  throw new Error('An explicit approved production or localhost URL is required');
}
if (process.env.DATA_ROOT && !/^http:\/\/localhost:\d+$/.test(base)) {
  throw new Error('An alternate expected-data directory is allowed only for an isolated localhost rehearsal');
}
const root = path.resolve(process.env.DATA_ROOT || fileURLToPath(new URL('../public/data/', import.meta.url)));
const file = reference => {
  const resolved = path.resolve(root, reference);
  assert(resolved.startsWith(root + path.sep), 'Expected data must stay inside the approved data directory');
  return resolved;
};
const read = reference => JSON.parse(fs.readFileSync(file(reference), 'utf8'));
const manifest = read('manifest.json');
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
      const board = read(files.board);
      await page.getByRole('navigation').getByRole('button', { name: 'Player Rankings', exact: true }).click();
      await page.getByLabel('Rows', { exact: true }).selectOption('1000');
      assert.equal(await page.locator('table:visible tbody tr').count(), board.rows.length);
      for (const section of ['Parlay Builder', 'Market Check', 'Game Predictor', 'Game Breakdown', 'Dashboard']) {
        await page.getByRole('navigation').getByRole('button', { name: section, exact: true }).click();
        if (section === 'Game Predictor') {
          const panel = page.getByRole('region', { name: 'Game Predictor', exact: true });
          if (!files.game_predictor) {
            await panel.getByText('Game Predictor data has not been published for this week.', { exact: false }).waitFor();
            assert.equal(await panel.getByRole('heading', { name: 'Projected final score', exact: false }).count(), 0);
          } else {
            assert(files.game_predictor_sha256, 'Published game projections require a manifest hash');
            const artifact = read(files.game_predictor);
            const served = await page.request.get(base + '/data/' + files.game_predictor);
            assert.equal(served.status(), 200);
            const servedBytes = await served.body();
            assert.equal(crypto.createHash('sha256').update(servedBytes).digest('hex'), files.game_predictor_sha256);
            assert.deepEqual(servedBytes, fs.readFileSync(file(files.game_predictor)));
            assert.equal(artifact.meta.primary_method, 'baseline');
            assert.deepEqual(Object.keys(artifact.games).sort(), board.meta.games.map(g => g.game_id).sort());
            assert.equal(await page.getByLabel('Predictor matchup').locator('option').count(), board.meta.games.length);
            await panel.getByText('No win-probability claim', { exact: true }).waitFor();
            for (const game of board.meta.games) {
              await page.getByLabel('Predictor matchup').selectOption(game.game_id);
              const value = artifact.games[game.game_id];
              assert.equal(value.status, 'available', 'Published full-product projections must have verified scoring evidence');
              const projection = value.methods.baseline;
              assert.equal(projection.win_probability, null, 'PPP does not establish calibrated win probabilities');
              await panel.getByRole('button', { name: 'PPP Baseline', exact: true }).click();
              if (contentHealthOnly) {
                const freshness = gameFreshness(artifact, value, await page.evaluate(() => Date.now()));
                if (freshness.startsWith('Unavailable')) {
                  await panel.getByText(freshness, { exact: true }).waitFor();
                  await panel.getByText('Projection suppressed until fresh pregame sources are available.', { exact: true }).waitFor();
                  assert.equal(await panel.getByRole('heading', { name: 'Projected final score', exact: false }).count(), 0);
                  assert.equal(await panel.getByText('Predicted winner:', { exact: false }).count(), 0);
                  continue;
                }
              }
              await panel.getByRole('heading', { name: 'Projected final score · PPP Baseline', exact: true }).waitFor();
              for (const score of Object.values(projection.scores)) {
                assert(await panel.getByText(score.toFixed(1), { exact: true }).count() > 0);
              }
              await panel.getByText('Projected margin: ' + Math.abs(projection.home_margin).toFixed(1) + ' points · Projected total: ' + projection.total.toFixed(1) + ' points', { exact: false }).waitFor();
              const label = await page.getByLabel('Predictor matchup').locator('option:checked').textContent();
              const [awayName, homeName] = label.split(' @ ');
              const winner = projection.favored ? (projection.favored === value.away_team ? awayName : homeName) : 'No edge \u2014 equal projected means';
              await panel.getByText('Predicted winner: ' + winner, { exact: true }).waitFor();
              const experimental = panel.getByRole('button', { name: 'Adjusted Projection · Experimental', exact: true });
              if (value.methods.adjusted) {
                await experimental.waitFor();
                assert.equal(value.methods.adjusted.win_probability, null);
              } else {
                assert.equal(await experimental.count(), 0);
              }
            }
            assert.deepEqual((await panel.getByRole('alert').allTextContents()).filter(text => text.trim()), []);
          }
        }
        if (section === 'Game Breakdown') {
          await page.getByLabel('Game', { exact: true }).waitFor();
          for (const label of ['Offensive Identity', 'Defensive Vulnerabilities', 'TD Recommendations']) {
            await page.getByRole('group', { name: 'Game Breakdown sections' }).getByRole('button', { name: label, exact: true }).click();
            if (files.matchup_intelligence) {
              await page.getByRole('region', { name: label === 'TD Recommendations' ? 'Matchup-Based TD Recommendations' : label, exact: true }).waitFor();
              assert.deepEqual((await page.getByRole('alert').allTextContents()).filter(text => text.trim()), [], 'Published intelligence must validate and render');
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
  console.log('PASS ' + (contentHealthOnly ? 'SOURCE-ONLY content health (not release approval): ' : 'strict release verification: ') + 'actual served weeks, player coverage, Game Predictor availability or exact PPP values/hashes, Matchup Intelligence, mobile navigation and runtime errors; no intercepted responses');
} finally {
  await browser.close();
}

// Browser validation of an unpublished real candidate. Intercepts data requests only;
// never copies candidate files into public/data or changes the published manifest.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const loadPackage = createRequire(import.meta.url);
const { chromium } = loadPackage('playwright');
const folder = process.env.CANDIDATE_DIR;
if (!folder) throw new Error('Set CANDIDATE_DIR to an unpublished candidate directory');
const board = JSON.parse(fs.readFileSync(path.join(folder, 'board.json'), 'utf8'));
const breakdowns = JSON.parse(fs.readFileSync(path.join(folder, 'breakdowns.json'), 'utf8'));
const { season, week, generated_at, model, snapshot_classification } = board.meta;
const manifest = { schema_version: 1, supported_weeks: Array.from({length:18},(_,i)=>i+1), seasons: {
  [season]: { weeks: { [week]: { board:'review/board.json', breakdowns:'review/breakdowns.json', generated_at, model } } },
}};
const browser = await chromium.launch({channel:'chrome',headless:true});
try {
 const page = await browser.newPage({viewport:{width:390,height:844}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/data/manifest.json',r=>r.fulfill({json:manifest}));
 await page.route('**/data/review/board.json',r=>r.fulfill({json:board}));
 await page.route('**/data/review/breakdowns.json',r=>r.fulfill({json:breakdowns}));
 await page.goto(process.env.BASE_URL || 'http://localhost:3104');
 await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('Week',{exact:true}).inputValue(),String(week));
 await page.getByText(snapshot_classification==='historical_backfill'?'Historical backfill':'Pregame snapshot',{exact:true}).first().waitFor();
 await page.getByRole('navigation').getByRole('button',{name:'Player Rankings',exact:true}).click();
 await page.getByLabel('Rows',{exact:true}).selectOption('1000');
 assert.equal(await page.locator('table tbody tr').count(),board.rows.length);
 await page.getByRole('navigation').getByRole('button',{name:'Game Breakdown',exact:true}).click();
 await page.getByLabel('Game',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('Game',{exact:true}).locator('option').count(),Object.keys(breakdowns.games).length);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 assert.deepEqual(errors,[]);
 console.log(`PASS unpublished ${snapshot_classification}: ${board.rows.length} players, ${Object.keys(breakdowns.games).length} matchups; mobile rendering and no runtime errors`);
} finally {await browser.close()}

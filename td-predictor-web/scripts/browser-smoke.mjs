// Run against a production server: NODE_PATH=<Playwright package root> node scripts/browser-smoke.mjs
import { createRequire } from 'node:module';
const loadPackage = createRequire(import.meta.url);
const { chromium } = loadPackage('playwright');
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
(async () => {
 const browser = await chromium.launch({channel:'chrome', headless:true});
 const page = await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.BASE_URL || 'http://localhost:3104';
 const manifest=JSON.parse(fs.readFileSync('public/data/manifest.json','utf8'));
 const season=Object.keys(manifest.seasons).sort().at(-1);
 const week=Object.keys(manifest.seasons[season].weeks).map(Number).sort((a,b)=>a-b).at(-1);
 const board=JSON.parse(fs.readFileSync(path.join('public/data',manifest.seasons[season].weeks[week].board),'utf8'));
 const eligible=board.rows.filter(r=>r.game_status==='Upcoming').sort((a,b)=>b.td_estimate-a.td_estimate);
 const nav=label=>page.getByRole('navigation').getByRole('button',{name:label,exact:true}).click();
 const check=async(label,fn)=>{await fn();console.log('PASS '+label)};
 try {
 await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 await check('dashboard uses published snapshot',async()=>{assert.equal(await page.getByLabel('Week',{exact:true}).inputValue(),String(week));assert(await page.getByText(board.rows.slice().sort((a,b)=>b.td_estimate-a.td_estimate)[0].player,{exact:true}).count()>0)});
 await check('snapshot model version, classification and freshness are visible',async()=>{await page.getByRole('status',{name:'Data freshness'}).waitFor();if(board.meta.model_version)assert(await page.locator('[title]').filter({hasText:'Version:'}).count()>0);assert(await page.getByText(({pregame_snapshot:'Pregame snapshot',historical_backfill:'Historical backfill',mixed_pregame_and_historical:'Mixed pregame / historical'}[board.meta.snapshot_classification] ?? 'Classification unavailable'),{exact:true}).count()>0)});
 await page.screenshot({path:'../work/dashboard-desktop.png',fullPage:true});
 await nav('Player Rankings');
 await check('rankings search and empty state',async()=>{await page.getByLabel('Search player',{exact:true}).fill('zzzz-no-player');await page.getByText('No players match these filters.').waitFor();await page.getByLabel('Search player',{exact:true}).fill('')});
 await check('sorting and filters',async()=>{await page.getByLabel('Sort by').selectOption('ascending');let vals=await page.locator('table tbody tr').evaluateAll(rows=>rows.map(r=>parseFloat(r.cells[6].textContent)));assert(vals.every((v,i)=>!i||v>=vals[i-1]));await page.getByLabel('Team',{exact:true}).selectOption(board.rows[0].team);assert((await page.locator('table tbody tr').count())>0);await page.getByLabel('Team',{exact:true}).selectOption('ALL');await page.getByLabel('Injury status').selectOption('Unknown');await page.getByLabel('Injury status').selectOption('ALL')});
 await nav('Parlay Builder');
 if(eligible.length>=2){await check('manual parlay selection, probability, removal, navigation retention',async()=>{for(const p of eligible.slice(0,2)){await page.getByRole('textbox',{name:'Search players'}).fill(p.player);await page.locator('button').filter({has:page.locator('strong',{hasText:p.player})}).first().click()}await page.getByText('All legs hit',{exact:true}).waitFor();const expected=eligible[0].td_estimate*eligible[1].td_estimate/100;const formatted=expected>=1?expected.toFixed(2)+'%':expected.toFixed(3)+'%';assert(await page.getByText(formatted,{exact:true}).count()>0);await nav('Dashboard');await nav('Parlay Builder');await page.getByText('All legs hit',{exact:true}).waitFor();await page.getByRole('button',{name:'Remove '+eligible[0].player,exact:true}).click();await page.getByText('Add at least one more leg to see a combined probability.').waitFor()});
 await check('automatic parlay',async()=>{await page.getByRole('button',{name:'Auto-build for me'}).click();await page.getByRole('button',{name:'Suggest a parlay'}).click();await page.getByText('All legs hit',{exact:true}).waitFor()});}
 await nav('Market Check');
 await check('market validates odds and compares actual player',async()=>{await page.getByRole('button',{name:'Add',exact:true}).click();await page.getByText('Pick a player first.').waitFor();if(eligible.length){const p=eligible[0];await page.getByRole('textbox',{name:'Search players'}).fill(p.player);await page.locator('button').filter({has:page.locator('strong',{hasText:p.player})}).first().click();await page.getByLabel('Anytime TD odds').fill('invalid');await page.getByRole('button',{name:'Add',exact:true}).click();await page.getByText("Couldn't read those odds",{exact:false}).waitFor();await page.getByLabel('Anytime TD odds').fill('+150');await page.getByRole('button',{name:'Add',exact:true}).click();await page.getByRole('cell',{name:'40.0%',exact:true}).waitFor();}});
 await nav('Game Breakdown');
 await check('breakdown matchup and team switch',async()=>{await page.getByLabel('Game',{exact:true}).waitFor();const options=await page.getByLabel('Game',{exact:true}).locator('option').all();assert(options.length>0);if(options.length>1)await page.getByLabel('Game',{exact:true}).selectOption({index:1});const teams=page.getByRole('group',{name:'Team',exact:true}).getByRole('button');await teams.nth(1).click();assert.equal(await teams.nth(1).getAttribute('aria-pressed'),'true')});
 await check('missing week never displays stale predictions',async()=>{await page.getByLabel('Week',{exact:true}).selectOption('1');await page.getByText('have not been generated yet.',{exact:false}).waitFor();assert.equal(await page.getByText('GENERATED SNAPSHOT',{exact:false}).count(),0);await page.getByLabel('Week',{exact:true}).selectOption(String(week));await page.getByLabel('Game',{exact:true}).waitFor()});
 await page.setViewportSize({width:390,height:844});await nav('Dashboard');await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 await check('mobile layout and navigation',async()=>{assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));await page.screenshot({path:'../work/dashboard-mobile.png',fullPage:true});await nav('Player Rankings');await page.getByLabel('Search player',{exact:true}).waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));});
 await check('all published weeks load their own snapshot',async()=>{for(const w of Object.keys(manifest.seasons[season].weeks)){await page.getByLabel('Week',{exact:true}).selectOption(w);await page.getByText('GENERATED SNAPSHOT',{exact:false}).waitFor();assert(await page.getByText(`Week ${w} · ${season}`,{exact:true}).count()>0)}await page.getByLabel('Week',{exact:true}).selectOption(String(week));});
 await check('mobile tools stay within the viewport',async()=>{for(const section of ['Parlay Builder','Market Check','Game Breakdown']){await nav(section);if(section==='Game Breakdown')await page.getByLabel('Game',{exact:true}).waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),section)}});
 await check('malformed board rejected without a crash',async()=>{const broken=structuredClone(board);broken.meta.final_games=[null];await page.route('**/data/**/board.json',r=>r.fulfill({json:broken}));await page.reload();await page.getByRole('alert').filter({hasText:'Invalid injury or final-game metadata'}).waitFor();await page.unroute('**/data/**/board.json')});
 await check('malformed breakdown rejected without a crash',async()=>{await page.route('**/data/**/breakdowns.json',r=>r.fulfill({json:{meta:{season:Number(season),week},games:{bad:null},errors:{}}}));await page.reload();await page.getByText('Leading TD estimates',{exact:true}).waitFor();await nav('Game Breakdown');await page.getByText('The matchup breakdown contains invalid data.',{exact:false}).waitFor();await page.unroute('**/data/**/breakdowns.json')});
 await check('request failure state',async()=>{await page.route('**/data/manifest.json',r=>r.fulfill({status:503,body:'unavailable'}));await page.reload();await page.getByText('Prediction week index is unavailable or invalid',{exact:false}).waitFor();await page.unroute('**/data/manifest.json')});
 await check('malformed manifest handled safely',async()=>{await page.route('**/data/manifest.json',r=>r.fulfill({json:{schema_version:1,supported_weeks:[9],seasons:{2026:{weeks:null}}}}));await page.reload();await page.getByText('Prediction week index is unavailable or invalid',{exact:false}).waitFor();await page.unroute('**/data/manifest.json')});
 assert.deepEqual(errors,[]);console.log('PASS no browser runtime errors');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});

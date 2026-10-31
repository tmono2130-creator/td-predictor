// Actual existing published rows only. No generated predictions or intercepted data.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {latestGeneratedWeek} from '../lib/week-selection.ts';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.BASE_URL||'http://localhost:3138';
const manifest=JSON.parse(fs.readFileSync('public/data/manifest.json','utf8'));
const season=Object.keys(manifest.seasons).sort().at(-1),weeks=Object.keys(manifest.seasons[season].weeks),week=latestGeneratedWeek(manifest.seasons[season].weeks,manifest.supported_weeks[0] ?? 1);
const board=JSON.parse(fs.readFileSync('public/data/'+manifest.seasons[season].weeks[week].board,'utf8'));
const teams=[...new Set(board.rows.map(r=>r.team))].sort().slice(0,3);
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('Week',{exact:true}).inputValue(),String(week));
 const nav=label=>page.getByRole('navigation').getByRole('button',{name:label,exact:true}).click();
 await nav('Player Rankings');await page.getByLabel('Rows',{exact:true}).selectOption('1000');
 await page.locator('summary').filter({hasText:'Teams ·'}).click();
 const group=page.getByRole('group',{name:'Filter teams'});assert.equal(await group.getByRole('checkbox').count(),32);
 for(let i=0;i<3;i++){
  await group.getByRole('checkbox').evaluateAll((els,team)=>els.find(e=>e.getAttribute('aria-label').endsWith('('+team+')')).click(),teams[i]);
  if(i>=1)assert.equal(await page.locator('table tbody tr').count(),board.rows.filter(r=>teams.slice(0,i+1).includes(r.team)).length);
 }
 await page.locator('summary').filter({hasText:'Teams ·'}).click();
 assert.equal(await page.getByRole('group',{name:'Selected teams'}).getByRole('button').count(),4);
 await page.getByLabel('Sort by').selectOption('ascending');await page.getByLabel('Injury status').selectOption('Unknown');
 const selected=board.rows.filter(r=>teams.includes(r.team)&&r.injury_status==='Unknown');assert.equal(await page.locator('table tbody tr').count(),selected.length);
 const player=selected.find(r=>r.game_status==='Upcoming');
 if(player){await page.getByLabel('Search player',{exact:true}).fill(player.player);assert(await page.locator('table tbody tr').count()>0);await page.getByRole('button',{name:'Add '+player.player+' to parlay',exact:true}).click();await nav('Parlay Builder');await page.getByRole('button',{name:'Remove '+player.player,exact:true}).waitFor();await nav('Player Rankings');}
 await page.getByLabel('Search player',{exact:true}).fill('zzzzz-no-player');await page.getByText('No players match these filters.').waitFor();await page.getByLabel('Search player',{exact:true}).fill('');
 await page.getByLabel('Injury status').selectOption('ALL');
 await page.screenshot({path:process.env.SCREENSHOT_DIR+'/multi-team-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.locator('summary').filter({hasText:'Teams ·'}).click();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:process.env.SCREENSHOT_DIR+'/multi-team-mobile.png',fullPage:false});
 for(const el of await group.getByRole('checkbox').all())await el.check();assert.equal(await page.locator('table tbody tr').count(),board.rows.length);
 await page.getByRole('button',{name:'All Teams / Clear Selection',exact:true}).click();assert.equal(await page.locator('table tbody tr').count(),board.rows.length);
 await group.getByRole('checkbox').first().check();
 const alternate=weeks.find(w=>Number(w)!==week);if(alternate){await page.getByLabel('Week',{exact:true}).selectOption(alternate);await page.getByText('Week '+alternate+' · '+season,{exact:true}).waitFor();await page.locator('summary').filter({hasText:'Teams · All Teams'}).waitFor();}
 assert.deepEqual(errors,[]);console.log('PASS two/three/all32 teams, reset, combined search/sort/injury filters, empty state, week reset, Add-to-Parlay, mobile and runtime checks');
}finally{await browser.close()}

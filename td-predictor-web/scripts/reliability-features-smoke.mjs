// Isolated browser checks only: synthetic evaluation fallback is never written to public/.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {latestGeneratedWeek} from '../lib/week-selection.ts';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.BASE_URL||'http://localhost:3191';
const manifest=JSON.parse(fs.readFileSync('public/data/manifest.json','utf8'));
const season=Object.keys(manifest.seasons).sort().at(-1),week=latestGeneratedWeek(manifest.seasons[season].weeks,1);
const board=JSON.parse(fs.readFileSync(path.join('public/data',manifest.seasons[season].weeks[week].board),'utf8'));
const emptyScore={n:0,winner_accuracy:null,team_score_mae:null,total_mae:null,margin_mae:null};
const emptyTd={n:0,positives:0,brier:null,log_loss:null,auc:null,calibration:[]};
const gid='2026_09_BUF_MIN';
const synthetic={schema_version:1,evaluation_id:'a'.repeat(24),season:2026,week:9,status:'partial',evaluated_as_of:'2026-11-09T19:00:00Z',forecast_generated_at:'2026-11-05T20:00:00Z',forecast_hashes:{'board.json':'b'.repeat(64),'receipt.json':'c'.repeat(64)},games_completed:0,games_pending:1,game_metrics:emptyScore,baseline_metrics:emptyScore,td_metrics:emptyTd,position_metrics:{QB:emptyTd},missing_labels:{pending_game:1},limitations:['SYNTHETIC BROWSER FIXTURE ONLY; never production'],games:[{game_id:gid,away_team:'BUF',home_team:'MIN',kickoff_utc:'2026-11-10T01:15:00Z',status:'pending',prediction:{away:22,home:21},actual:null}],players:[{game_id:gid,player_id:'00-0000001',player:'TEST PLAYER ONLY',team:'BUF',position:'QB',estimate_pct:20,actual_td:null,outcome_reason:'pending_game'}]};
const evaluation=process.env.EVALUATION_FIXTURE_FILE?JSON.parse(fs.readFileSync(process.env.EVALUATION_FIXTURE_FILE,'utf8')):synthetic;
const bytes=Buffer.from(JSON.stringify(evaluation)),pin=createHash('sha256').update(bytes).digest('hex');
const index={schema_version:1,reports:[{season:evaluation.season,week:evaluation.week,path:evaluation.evaluation_id+'/evaluation.json',sha256:pin}]};
const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL||'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 // Deterministic test clocks only; never a release eligibility claim.
 await page.clock.install({time:new Date(Date.parse(evaluation.evaluated_as_of)+1000)});
 await page.route('**/evaluations/index.json',r=>r.fulfill({status:404,body:'No reviewed evaluation'}));
 await page.goto(base);await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Model Performance',exact:true}).click();
 await page.getByText('No reviewed evaluations have been published.',{exact:false}).waitFor();
 await page.unroute('**/evaluations/index.json');
 await page.route('**/evaluations/index.json',r=>r.fulfill({json:index}));
 await page.route('**/evaluations/*/evaluation.json',r=>r.fulfill({body:bytes,contentType:'application/json'}));
 await page.reload();await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Model Performance',exact:true}).click();
 await page.getByLabel('Evaluation season and week').selectOption(`${evaluation.season}:${evaluation.week}`);
 await page.getByText(`${evaluation.status==='partial'?'Partial week':'Verified final evaluation'}: ${evaluation.games_completed} completed`,{exact:false}).waitFor();
 const performance=page.getByRole('region',{name:'Model performance',exact:true});
 assert.equal(await page.getByLabel('Week',{exact:true}).count(),0,'Performance uses its own evaluation selector, not prediction-week badges');
 assert.equal(await performance.getByText('Unknown / pending',{exact:true}).count(),evaluation.players.filter(p=>p.actual_td==null).length);
 assert(await performance.getByText('Actual away/home',{exact:true}).count());
 await page.getByLabel('Search evaluated players').fill(evaluation.players[0].player);assert(await performance.getByText(evaluation.players[0].player,{exact:true}).count());
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'performance at '+width);}
 const shots=process.env.SCREENSHOT_DIR;
 if(shots){fs.mkdirSync(shots,{recursive:true});await page.screenshot({path:path.join(shots,'performance-TEST-CONTEXT.png'),fullPage:true});}
 await page.clock.setFixedTime(new Date(Date.parse(board.meta.generated_at)+1000));
 await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Parlay Builder',exact:true}).click();
 await page.getByRole('button',{name:'Diversified combinations',exact:true}).click();
 await page.getByLabel('Number of combinations').selectOption('20');await page.getByRole('button',{name:'Generate combinations',exact:true}).click();
 const generator=page.getByRole('region',{name:'Diversified parlay generator',exact:true});
 await generator.getByText('Generated 20 of 20.',{exact:false}).waitFor();
 const firstTable=generator.getByRole('table').first();assert.equal(await firstTable.locator('tbody tr').count(),20);
 const combinations=await firstTable.locator('tbody tr').allTextContents();assert.equal(new Set(combinations.map(s=>s.replace(/^\d+/,''))).size,20);
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'generator at '+width);}
 if(shots)await page.screenshot({path:path.join(shots,'parlays-TEST-CONTEXT.png'),fullPage:true});
 await page.getByLabel('Maximum player exposure (%)').fill('1');await page.getByRole('button',{name:'Generate combinations',exact:true}).click();await generator.getByRole('alert').filter({hasText:'Exposure limit'}).waitFor();
 await page.unroute('**/evaluations/*/evaluation.json');await page.route('**/evaluations/*/evaluation.json',r=>r.fulfill({json:{...evaluation,status:'tampered'}}));
 await page.clock.setFixedTime(new Date(Date.parse(evaluation.evaluated_as_of)+1000));
 await page.reload();await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Model Performance',exact:true}).click();await page.getByLabel('Evaluation season and week').selectOption(`${evaluation.season}:${evaluation.week}`);
 await page.getByRole('alert').filter({hasText:'Evaluation hash mismatch'}).waitFor();assert.equal(await page.getByText('TD Brier',{exact:true}).count(),0);
 assert.deepEqual(errors,[]);
 console.log('PASS evaluation empty/verified/pending/tampered states; diversified 20-combination batch, exposure failure, responsive 320/390/768/1440px and no runtime errors.');
 console.log(process.env.EVALUATION_FIXTURE_FILE?'Evaluation fixture: real frozen pregame forecasts + separately verified postgame labels, local routing only.':'Evaluation fixture: synthetic test-only; not a hosted outcome evaluation.');
}finally{await browser.close();}

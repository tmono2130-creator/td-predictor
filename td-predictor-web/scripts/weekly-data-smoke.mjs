// Local unpublished capture inspection only; all responses are browser-intercepted.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fairAmericanOdds} from '../lib/parlay.ts';
import {TEAM_NAMES} from '../lib/data.ts';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.BASE_URL;
if(!/^http:\/\/localhost:\d+$/.test(base||'')||!process.env.CANDIDATE_DIR)throw new Error('Explicit localhost and unpublished candidate required');
const root=path.resolve(process.env.CANDIDATE_DIR),bytes={};
for(const name of ['board.json','breakdowns.json','receipt.json','game-predictor.json','matchup-intelligence.json'])bytes[name]=fs.readFileSync(path.join(root,name));
const board=JSON.parse(bytes['board.json']),gp=JSON.parse(bytes['game-predictor.json']),mi=JSON.parse(bytes['matchup-intelligence.json']),receipt=JSON.parse(bytes['receipt.json']);
assert(receipt.bundle_status.three_features);
assert(board.rows.every(r=>r.actual_scored_td===null));
const digest=name=>crypto.createHash('sha256').update(bytes[name]).digest('hex');
for(const [name,key] of [['board.json','board_sha256'],['breakdowns.json','breakdowns_sha256'],['game-predictor.json','game_predictor_sha256'],['matchup-intelligence.json','matchup_intelligence_sha256']])assert.equal(receipt[key],digest(name));
const byId=new Map(board.rows.map(r=>[r.player_id+':'+r.game_id,r]));
assert.equal(byId.size,board.rows.length);
for(const game of Object.values(mi.games))for(const r of game.recommendations){const p=byId.get(r.player_id+':'+r.game_id);assert(p);assert.equal(r.v5_probability_pct,p.td_estimate);assert.equal(r.team,p.team);assert.equal(r.opponent,p.opponent);}
for(const value of [gp,mi])assert.deepEqual(Object.keys(value.games).sort(),board.meta.games.map(g=>g.game_id).sort());
assert.equal(gp.meta.primary_method,'baseline');
for(const game of Object.values(gp.games)){assert.equal(game.methods.baseline.win_probability,null);assert.equal(game.methods.adjusted,undefined);}
// Preserve real legacy weeks too: a newly published Week 8 must win default
// selection over a numerically higher but older Week 9 snapshot.
const manifest=JSON.parse(fs.readFileSync(new URL('../public/data/manifest.json',import.meta.url),'utf8'));
manifest.seasons[board.meta.season]??={weeks:{}};
manifest.seasons[board.meta.season].weeks[board.meta.week]={
 board:'review/board.json',breakdowns:'review/breakdowns.json',generated_at:board.meta.generated_at,model:board.meta.model,
 game_predictor:'review/game-predictor.json',game_predictor_sha256:digest('game-predictor.json'),
 matchup_intelligence:'review/matchup-intelligence.json',matchup_intelligence_sha256:digest('matchup-intelligence.json')
};
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.setDefaultTimeout(15_000);
 page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date(board.meta.generated_at)});
 let activeManifest=manifest,failedFile=null,brokenBoard=false;
 await page.route('**/data/manifest.json',r=>r.fulfill({json:activeManifest}));
 await page.route('**/data/review/*',r=>{const name=new URL(r.request().url()).pathname.split('/').at(-1);if(name===failedFile)return r.fulfill({status:503,body:'TEST: unavailable'});if(name==='board.json'&&brokenBoard)return r.fulfill({json:{...board,meta:{...board.meta,final_games:[null]}}});return bytes[name]?r.fulfill({body:bytes[name],contentType:'application/json'}):r.fulfill({status:404});});
 const nav=label=>page.getByRole('navigation').getByRole('button',{name:label,exact:true}).click();
 const check=async(label,fn)=>{try{await fn();console.log('PASS real bundle: '+label);}catch(error){console.error('FAILED real bundle: '+label+'\n'+(await page.locator('body').innerText()).slice(-9000));throw error;}};
 const rows=()=>page.locator('table:visible tbody tr');
 const leader=board.rows.slice().sort((a,b)=>b.td_estimate-a.td_estimate)[0];
 await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 await check('season/week, fresh snapshot, exact V5 leader',async()=>{
  assert.equal(await page.getByLabel('Season',{exact:true}).inputValue(),String(board.meta.season));assert.equal(await page.getByLabel('Week',{exact:true}).inputValue(),String(board.meta.week));
  await page.getByRole('status',{name:'Data freshness'}).filter({hasText:'Within refresh window'}).waitFor();
  const featured=page.getByLabel('Featured player estimates').locator('section').first();assert.equal(await featured.locator('h3').textContent(),leader.player);assert.equal(await featured.locator('[style]').evaluate(el=>parseFloat(el.style.width)),leader.td_estimate);
 });
 await nav('Player Rankings');await page.getByLabel('Rows',{exact:true}).selectOption('1000');
 await check('all rows, sorting, search, player details, multiple teams and all32-team controls',async()=>{
  assert.equal(await rows().count(),board.rows.length);await page.getByLabel('Sort by').selectOption('ascending');const values=await rows().evaluateAll(rs=>rs.map(r=>parseFloat(r.cells[6].textContent)));assert(values.every((v,i)=>!i||v>=values[i-1]));
  const teams=[...new Set(board.rows.map(r=>r.team))].sort().slice(0,3);await page.locator('summary').filter({hasText:'Teams ·'}).click();const group=page.getByRole('group',{name:'Filter teams'});assert.equal(await group.getByRole('checkbox').count(),32);
  for(const team of teams)await group.getByRole('checkbox',{name:new RegExp('\\('+team+'\\)$')}).check();assert.equal(await rows().count(),board.rows.filter(r=>teams.includes(r.team)).length);
  for(const box of await group.getByRole('checkbox').all())await box.check();assert.equal(await rows().count(),board.rows.length);await page.getByRole('button',{name:'All Teams / Clear Selection',exact:true}).click();
  const absent=Object.keys(TEAM_NAMES).find(team=>!board.rows.some(r=>r.team===team));
  if(absent){await group.getByRole('checkbox',{name:new RegExp('\\('+absent+'\\)$')}).check();await page.getByText('No players match these filters.').waitFor();await page.getByRole('button',{name:'All Teams / Clear Selection',exact:true}).click();}
  await page.locator('summary').filter({hasText:'Teams ·'}).click();
  await page.getByLabel('Injury status').selectOption('Unknown');assert.equal(await rows().count(),board.rows.filter(r=>r.injury_status==='Unknown').length);await page.getByLabel('Injury status').selectOption('ALL');
  await page.getByLabel('Search player',{exact:true}).fill('zzzz-no-player');await page.getByText('No players match these filters.').waitFor();await page.getByLabel('Search player',{exact:true}).fill(leader.player);const row=rows().filter({has:page.getByText(leader.player,{exact:true})});assert.equal(await row.count(),1);await row.locator('summary').click();await row.getByText('Outcome unavailable',{exact:false}).waitFor();
 });
 await check('Add-to-Parlay, exact combined probability, removal, navigation retention and auto-build',async()=>{
  await page.getByRole('button',{name:'Add '+leader.player+' to parlay',exact:true}).click();await nav('Parlay Builder');await page.getByRole('button',{name:'Remove '+leader.player,exact:true}).waitFor();const other=board.rows.find(p=>p.player_id!==leader.player_id&&p.team!==leader.team);await page.getByRole('textbox',{name:'Search players'}).fill(other.player);await page.locator('button').filter({has:page.locator('strong',{hasText:other.player})}).first().click();const probability=leader.td_estimate*other.td_estimate/100;await page.getByText(probability.toFixed(probability>=1?2:3)+'%',{exact:true}).waitFor();await nav('Dashboard');await nav('Parlay Builder');await page.getByText('All legs hit',{exact:true}).waitFor();await page.getByRole('button',{name:'Remove '+other.player,exact:true}).click();await page.getByText('Add at least one more leg to see a combined probability.').waitFor();await page.getByRole('button',{name:'Auto-build for me'}).click();await page.getByRole('button',{name:'Suggest a parlay'}).click();await page.getByText('All legs hit',{exact:true}).waitFor();
 });
 await nav('Market Check');
 await check('Market Check fair odds, 40% implied probability, model gap and invalid-input states',async()=>{
  await page.getByRole('button',{name:'Add',exact:true}).click();await page.getByText('Pick a player first.').waitFor();await page.getByRole('textbox',{name:'Search players'}).fill(leader.player);await page.locator('button').filter({has:page.locator('strong',{hasText:leader.player})}).first().click();await page.getByLabel('Anytime TD odds').fill('invalid');await page.getByRole('button',{name:'Add',exact:true}).click();await page.getByText("Couldn't read those odds",{exact:false}).waitFor();await page.getByLabel('Anytime TD odds').fill('+150');await page.getByRole('button',{name:'Add',exact:true}).click();const cells=rows().first().locator('td');assert.equal(await cells.nth(1).textContent(),leader.td_estimate.toFixed(1)+'%');assert.equal(await cells.nth(2).textContent(),fairAmericanOdds(leader.td_estimate));assert.equal(await cells.nth(4).textContent(),'40.0%');assert.equal(await cells.nth(5).textContent(),(leader.td_estimate>=40?'+':'')+(leader.td_estimate-40).toFixed(1)+' pts');
 });
 await page.getByRole('navigation').getByRole('button',{name:'Game Predictor',exact:true}).click();
 await page.getByRole('heading',{name:'Projected final score · PPP Baseline',exact:true}).waitFor();
 assert.equal(await page.getByLabel('Predictor matchup').locator('option').count(),board.meta.games.length);
 const first=gp.games[board.meta.games[0].game_id];
 for(const score of Object.values(first.methods.baseline.scores))assert(await page.getByText(score.toFixed(1),{exact:true}).count()>0);
 assert.equal(await page.getByRole('button',{name:'Adjusted Projection · Experimental',exact:true}).count(),0);
 await check('every PPP game renders exact scores, favored team, projected margin and total',async()=>{
  const panel=page.getByRole('region',{name:'Game Predictor',exact:true});await panel.getByText('No win-probability claim',{exact:true}).waitFor();assert(gp.meta.warnings.some(w=>w.includes('Adjusted model experimental')&&w.includes('no calibrated win probabilities')));
  for(const scheduled of board.meta.games){await page.getByLabel('Predictor matchup').selectOption(scheduled.game_id);const projection=gp.games[scheduled.game_id].methods.baseline;for(const score of Object.values(projection.scores))assert(await panel.getByText(score.toFixed(1),{exact:true}).count()>0);await panel.getByText('Projected margin: '+Math.abs(projection.home_margin).toFixed(1)+' points · Projected total: '+projection.total.toFixed(1)+' points',{exact:false}).waitFor();await panel.getByText('Predicted winner: '+(projection.favored?TEAM_NAMES[projection.favored]:'No edge \u2014 equal projected means'),{exact:true}).waitFor();await panel.getByText('Cutoff '+gp.meta.data_cutoff,{exact:false}).waitFor();}
 });
 await page.getByRole('navigation').getByRole('button',{name:'Game Breakdown',exact:true}).click();
 await page.getByRole('group',{name:'Game Breakdown sections'}).getByRole('button',{name:'Offensive Identity',exact:true}).click();
 await page.getByText('Offensive Identity',{exact:true}).last().waitFor();
 await page.getByRole('group',{name:'Game Breakdown sections'}).getByRole('button',{name:'TD Recommendations',exact:true}).click();
 await page.getByRole('region',{name:'Matchup-Based TD Recommendations'}).waitFor();
 await check('all breakdown matchups, both-team evidence and unchanged recommendation probabilities',async()=>{
  assert.equal(await page.getByLabel('Game',{exact:true}).locator('option').count(),board.meta.games.length);const sections=page.getByRole('group',{name:'Game Breakdown sections'});
  for(const scheduled of board.meta.games){await page.getByLabel('Game',{exact:true}).selectOption(scheduled.away_team+'@'+scheduled.home_team);await sections.getByRole('button',{name:'TD Breakdown',exact:true}).click();await page.getByText('Team scoring profile',{exact:true}).waitFor();for(const name of ['Offensive Identity','Defensive Vulnerabilities']){await sections.getByRole('button',{name,exact:true}).click();await page.getByRole('region',{name,exact:true}).waitFor();}await sections.getByRole('button',{name:'TD Recommendations',exact:true}).click();for(const team of [scheduled.away_team,scheduled.home_team]){await page.getByRole('group',{name:'Intelligence team'}).getByRole('button',{name:new RegExp('^'+team+' offense')}).click();const expectedRecommendations=mi.games[scheduled.game_id].recommendations.filter(p=>p.team===team);const rendered=page.getByRole('region',{name:'Matchup-Based TD Recommendations',exact:true}).locator('article');assert.equal(await rendered.count(),expectedRecommendations.length);const r=expectedRecommendations[0];if(r){const card=page.locator('article').filter({has:page.getByRole('heading',{name:r.player,exact:true})});await card.getByText(r.advantage,{exact:true}).waitFor();await card.getByText(r.v5_probability_pct.toFixed(1)+'%',{exact:true}).waitFor();assert(await card.locator('li').count()>0);}}}
 });
 // Next's route announcer is an empty ARIA alert, not an application error.
 assert.deepEqual((await page.getByRole('alert').allTextContents()).filter(text=>text.trim()),[]);
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});for(const section of ['Dashboard','Player Rankings','Parlay Builder','Market Check','Game Breakdown','Game Predictor']){await nav(section);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),section+' at '+width);}}
 await check('unpublished weeks show unavailable and do not reuse the candidate',async()=>{await page.getByLabel('Week',{exact:true}).selectOption(board.meta.week===1?'2':'1');await page.getByText('have not been generated yet.',{exact:false}).waitFor();assert.equal(await page.getByText('Projected final score',{exact:false}).count(),0);await page.getByLabel('Week',{exact:true}).selectOption(String(board.meta.week));await page.getByLabel('Predictor matchup').waitFor();});
 await check('missing sidecars and failed requests fail closed; no fallback predictions',async()=>{
  activeManifest=structuredClone(manifest);const files=activeManifest.seasons[board.meta.season].weeks[board.meta.week];for(const key of ['game_predictor','game_predictor_sha256','matchup_intelligence','matchup_intelligence_sha256'])delete files[key];await page.reload();await page.getByText('Leading TD estimates',{exact:true}).waitFor();await nav('Game Predictor');await page.getByText('Game Predictor data has not been published for this week.',{exact:false}).waitFor();await nav('Game Breakdown');await page.getByRole('button',{name:'Offensive Identity',exact:true}).click();await page.getByText('Matchup Intelligence has not been published for this snapshot.',{exact:false}).waitFor();activeManifest=manifest;
  for(const [file,section,message] of [['game-predictor.json','Game Predictor','Game Predictor unavailable:'],['matchup-intelligence.json','Game Breakdown','Matchup Intelligence unavailable:']]){failedFile=file;await page.reload();await page.getByText('Leading TD estimates',{exact:true}).waitFor();await nav(section);if(section==='Game Breakdown')await page.getByRole('button',{name:'Offensive Identity',exact:true}).click();await page.getByRole('alert').filter({hasText:message}).waitFor();}failedFile=null;
 });
 await check('invalid core data rejected safely',async()=>{brokenBoard=true;await page.reload();await page.getByRole('alert').filter({hasText:'Invalid injury or final-game metadata'}).waitFor();brokenBoard=false;});
 await page.reload();await page.getByText('Leading TD estimates',{exact:true}).waitFor();assert.deepEqual((await page.getByRole('alert').allTextContents()).filter(text=>text.trim()),[]);
 await check('stale pregame projections and recommendations are suppressed',async()=>{
  await page.clock.setSystemTime(Date.parse(board.meta.generated_at)+7*3_600_000);await page.clock.runFor(61_000);
  await nav('Game Predictor');await page.getByText('Projection suppressed until fresh pregame sources are available.',{exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'Projected final score · PPP Baseline',exact:true}).count(),0);
  await nav('Game Breakdown');await page.getByRole('button',{name:'TD Recommendations',exact:true}).click();await page.getByText('No current favorable/unfavorable recommendation is shown.',{exact:false}).waitFor();
 });
 await check('post-kickoff projections are explicitly archived forecasts',async()=>{await page.clock.setSystemTime(Date.parse(board.meta.games[0].kickoff_utc)+60_000);await page.clock.runFor(1001);await nav('Game Predictor');await page.getByText('Archived forecast — kickoff has passed',{exact:true}).waitFor();});
 assert.deepEqual(errors,[]);
 console.log(`PASS complete unpublished captured bundle: ${board.meta.games.length} games, ${board.rows.length} players; rankings, multi-team, parlay, market, every PPP and intelligence matchup, mobile and safe unavailable/error states. No production data served or changed.`);
}finally{await browser.close();}

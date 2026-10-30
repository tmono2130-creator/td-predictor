// Intercepted TEST FIXTURE only. No publication, public-data writes or live API.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const folder=process.env.MATCHUP_FIXTURE_DIR;if(!folder)throw new Error('Set MATCHUP_FIXTURE_DIR to explicit test-only fixtures');
const original=JSON.parse(fs.readFileSync(path.join(folder,'m7-fixture-artifact.json'),'utf8'));
const board=JSON.parse(fs.readFileSync(path.join(folder,'m7-fixture-board.json'),'utf8'));
assert(original.meta.limitations.some(v=>v.includes('TEST FIXTURE')),'Only labeled test fixtures may be intercepted');
const reports={meta:{season:board.meta.season,week:board.meta.week,generated_at:board.meta.generated_at,lookback:6},games:{},errors:{}};
for(const g of board.meta.games)reports.games[`${g.away_team}@${g.home_team}`]={teams:[g.away_team,g.home_team],offense:[],defense:[],players:{[g.away_team]:{},[g.home_team]:{}},injuries:{},flags:[],meta:{lookback:6,games_used:{[g.away_team]:0,[g.home_team]:0},prior_season_games:{[g.away_team]:0,[g.home_team]:0}}};
let artifact=structuredClone(original),badHash=false;
const bytes=()=>JSON.stringify(artifact);
const manifest=()=>({schema_version:1,supported_weeks:Array.from({length:18},(_,i)=>i+1),seasons:{[board.meta.season]:{weeks:{[board.meta.week]:{board:'review/board.json',breakdowns:'review/breakdowns.json',generated_at:board.meta.generated_at,model:'composite',matchup_intelligence:'review/matchup-intelligence.json',matchup_intelligence_sha256:badHash?'0'.repeat(64):crypto.createHash('sha256').update(bytes()).digest('hex')}}}}});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date(original.meta.generated_at)});
 await page.route('**/data/manifest.json',r=>r.fulfill({json:manifest()}));
 await page.route('**/data/review/board.json',r=>r.fulfill({json:board}));
 await page.route('**/data/review/breakdowns.json',r=>r.fulfill({json:reports}));
 await page.route('**/data/review/matchup-intelligence.json',r=>r.fulfill({body:bytes(),contentType:'application/json'}));
 const base=process.env.BASE_URL||'http://localhost:3117';
 const open=async()=>{await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();await page.getByRole('navigation').getByRole('button',{name:'Game Breakdown',exact:true}).click();await page.getByLabel('Game',{exact:true}).waitFor();};
 const section=label=>page.getByRole('group',{name:'Game Breakdown sections'}).getByRole('button',{name:label,exact:true}).click();
 const cleanShot=async()=>{await page.addStyleTag({content:'nextjs-portal { display:none !important; }'});await page.evaluate(()=>{if(document.activeElement instanceof HTMLElement)document.activeElement.blur();window.scrollTo(0,0);});};
 const loaded=()=>page.getByText('TEST FIXTURE — synthetic regression data, not real NFL statistics.',{exact:true}).first().waitFor();
 await open();await section('Offensive Identity');await loaded();await page.getByText('Player opportunity shares',{exact:true}).waitFor();
 const screenshots=process.env.SCREENSHOT_DIR||folder;await cleanShot();await page.screenshot({path:path.join(screenshots,'matchup-offense-test-fixture.png'),fullPage:true});
 await section('Defensive Vulnerabilities');await page.getByText('Allowed opportunities by offensive position',{exact:true}).waitFor();await cleanShot();await page.screenshot({path:path.join(screenshots,'matchup-defense-test-fixture.png'),fullPage:true});
 await section('TD Recommendations');await page.getByText('Favorable',{exact:true}).waitFor();await page.getByRole('region',{name:'Matchup-Based TD Recommendations'}).getByText('25.1%',{exact:true}).first().waitFor();await cleanShot();await page.screenshot({path:path.join(screenshots,'matchup-recommendations-test-fixture.png'),fullPage:true});
 await page.getByRole('group',{name:'Intelligence team'}).getByRole('button',{name:'WAS offense vs SF defense',exact:true}).click();await page.getByText('Unfavorable',{exact:true}).waitFor();
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});for(const name of ['Offensive Identity','Defensive Vulnerabilities','TD Recommendations']){await section(name);await loaded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} at ${width}`);}}
 await page.setViewportSize({width:390,height:844});await cleanShot();await page.screenshot({path:path.join(screenshots,'matchup-mobile-test-fixture.png'),fullPage:true});
 await page.clock.setFixedTime(new Date('2024-11-02T12:00:00Z'));await section('Offensive Identity');await section('TD Recommendations');await page.getByText('Stale analysis — refresh required before a recommendation',{exact:false}).first().waitFor();assert.equal(await page.getByText('Favorable',{exact:true}).count(),0);
 await page.clock.setFixedTime(new Date(original.meta.generated_at));
 for(const [label,mutate,hashMismatch] of [
  ['V5 mismatch',a=>a.games['2024_09_SF_WAS'].recommendations[0].v5_probability_pct=99,false],
  ['future cutoff',a=>a.meta.data_as_of='2025-01-01T00:00:00Z',false],
  ['hash mismatch',()=>{},true]
 ]){artifact=structuredClone(original);mutate(artifact);badHash=hashMismatch;await open();await section('TD Recommendations');await page.getByRole('alert').filter({hasText:'Matchup Intelligence unavailable'}).waitFor();console.log('PASS safe failure: '+label);}
 assert.deepEqual(errors,[]);console.log('PASS integrated offense/defense/recommendations, exact V5 display, team switching, stale suppression, 320/390/768/1440px, and no runtime errors; screenshots explicitly TEST FIXTURE');
}finally{await browser.close()}

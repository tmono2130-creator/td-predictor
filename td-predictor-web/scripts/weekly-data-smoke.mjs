// Local unpublished capture inspection only; all responses are browser-intercepted.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.BASE_URL;
if(!/^http:\/\/localhost:\d+$/.test(base||'')||!process.env.CANDIDATE_DIR)throw new Error('Explicit localhost and unpublished candidate required');
const root=path.resolve(process.env.CANDIDATE_DIR),bytes={};
for(const name of ['board.json','breakdowns.json','receipt.json','game-predictor.json','matchup-intelligence.json'])bytes[name]=fs.readFileSync(path.join(root,name));
const board=JSON.parse(bytes['board.json']),gp=JSON.parse(bytes['game-predictor.json']),receipt=JSON.parse(bytes['receipt.json']);
assert(receipt.bundle_status.three_features);
assert(board.rows.every(r=>r.actual_scored_td===null));
const digest=name=>crypto.createHash('sha256').update(bytes[name]).digest('hex');
const manifest={schema_version:1,supported_weeks:Array.from({length:18},(_,i)=>i+1),seasons:{[board.meta.season]:{weeks:{[board.meta.week]:{
 board:'review/board.json',breakdowns:'review/breakdowns.json',generated_at:board.meta.generated_at,model:board.meta.model,
 game_predictor:'review/game-predictor.json',game_predictor_sha256:digest('game-predictor.json'),
 matchup_intelligence:'review/matchup-intelligence.json',matchup_intelligence_sha256:digest('matchup-intelligence.json')
}}}}};
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date(board.meta.generated_at)});
 await page.route('**/data/manifest.json',r=>r.fulfill({json:manifest}));
 await page.route('**/data/review/*',r=>{const name=new URL(r.request().url()).pathname.split('/').at(-1);return bytes[name]?r.fulfill({body:bytes[name],contentType:'application/json'}):r.fulfill({status:404});});
 await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 await page.getByRole('navigation').getByRole('button',{name:'Game Predictor',exact:true}).click();
 await page.getByRole('heading',{name:'Projected final score · PPP Baseline',exact:true}).waitFor();
 assert.equal(await page.getByLabel('Predictor matchup').locator('option').count(),board.meta.games.length);
 const first=gp.games[board.meta.games[0].game_id];
 for(const score of Object.values(first.methods.baseline.scores))assert(await page.getByText(score.toFixed(1),{exact:true}).count()>0);
 assert.equal(await page.getByRole('button',{name:'Adjusted Projection · Experimental',exact:true}).count(),0);
 await page.getByRole('navigation').getByRole('button',{name:'Game Breakdown',exact:true}).click();
 await page.getByRole('group',{name:'Game Breakdown sections'}).getByRole('button',{name:'Offensive Identity',exact:true}).click();
 await page.getByText('Offensive Identity',{exact:true}).last().waitFor();
 await page.getByRole('group',{name:'Game Breakdown sections'}).getByRole('button',{name:'TD Recommendations',exact:true}).click();
 await page.getByRole('region',{name:'Matchup-Based TD Recommendations'}).waitFor();
 // Next's route announcer is an empty ARIA alert, not an application error.
 assert.deepEqual((await page.getByRole('alert').allTextContents()).filter(text=>text.trim()),[]);
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 assert.deepEqual(errors,[]);
 console.log(`PASS unpublished captured bundle: ${board.meta.games.length} games, ${board.rows.length} players; exact PPP scores, Matchup Intelligence, mobile and runtime checks. No production data served or changed.`);
}finally{await browser.close();}

// Read-only browser verification; optional historical review lives only in an isolated local test tree.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.BASE_URL||'http://localhost:3139';
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 await page.getByRole('navigation').getByRole('button',{name:'Game Predictor',exact:true}).click();
 await page.getByText('Game Predictor data has not been published for this week.',{exact:false}).waitFor();
 assert.equal(await page.getByText('Projected final score',{exact:false}).count(),0);
 const selector=page.getByLabel('Predictor matchup');assert(await selector.locator('option').count()>0);if(await selector.locator('option').count()>1)await selector.selectOption({index:1});
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 if(process.env.HISTORICAL_ARTIFACT){
  const artifact=JSON.parse(fs.readFileSync(process.env.HISTORICAL_ARTIFACT,'utf8'));assert.equal(artifact.meta.classification,'retrospective_analysis');
  await page.goto(base+'/game-review');await page.getByText('Retrospective analysis — original pregame vintage unverified',{exact:true}).waitFor();
  const g=artifact.games['2024_10_SF_TB'];await page.getByLabel('Predictor matchup').selectOption(g.game_id);
  for(const team of ['SF','TB'])assert(await page.getByText(g.methods.baseline.scores[team].toFixed(1),{exact:true}).count()>0);
  await page.getByText('Team Efficiency Comparison',{exact:true}).waitFor();
  await page.screenshot({path:process.env.SCREENSHOT_DIR+'/game-predictor-real-historical-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Adjusted Projection · Experimental',exact:true}).click();
  for(const team of ['SF','TB'])assert(await page.getByText(g.methods.adjusted.scores[team].toFixed(1),{exact:true}).count()>0);
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:process.env.SCREENSHOT_DIR+'/game-predictor-real-historical-mobile.png',fullPage:false});
  console.log('PASS real 2024 SF–TB reconstruction renders exact baseline/adjusted scores, sources, warnings and mobile layouts; explicitly NOT verified pregame data');
 }
 assert.deepEqual(errors,[]);console.log('PASS inactive Game Predictor, real schedule selector, no placeholder scores and no runtime errors');
}finally{await browser.close()}

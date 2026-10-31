// Read-only browser verification; optional historical review lives only in an isolated local test tree.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {latestGeneratedWeek} from '../lib/week-selection.ts';
import {validateGameArtifact,gameFreshness} from '../lib/game-projection.ts';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.BASE_URL||'http://localhost:3139';
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.getByText('Leading TD estimates',{exact:true}).waitFor();
 const manifest=JSON.parse(fs.readFileSync('public/data/manifest.json','utf8'));
 const season=Object.keys(manifest.seasons).sort().at(-1);
 assert.equal(await page.getByLabel('Week',{exact:true}).inputValue(),String(latestGeneratedWeek(manifest.seasons[season].weeks,manifest.supported_weeks[0] ?? 1)));
 for(const [season,entry] of Object.entries(manifest.seasons)){
  await page.getByLabel('Season',{exact:true}).selectOption(season);
  for(const [week,files] of Object.entries(entry.weeks)){
   await page.getByLabel('Week',{exact:true}).selectOption(week);
   await page.getByText('Week '+week+' · '+season,{exact:true}).waitFor();
   await page.getByRole('navigation').getByRole('button',{name:'Game Predictor',exact:true}).click();
   const panel=page.getByRole('region',{name:'Game Predictor',exact:true});
   const board=JSON.parse(fs.readFileSync(path.join('public/data',files.board),'utf8'));
   const selector=page.getByLabel('Predictor matchup');
   assert.deepEqual(await selector.locator('option').evaluateAll(els=>els.map(e=>e.value)),board.meta.games.map(g=>g.game_id));
   if(!files.game_predictor){
    await panel.getByText('Game Predictor data has not been published for this week.',{exact:false}).waitFor();
    assert.equal(await panel.getByRole('heading',{name:'Projected final score',exact:false}).count(),0);
   }else{
    assert(files.game_predictor_sha256,'Published sidecar must be pinned in the manifest');
    const bytes=fs.readFileSync(path.join('public/data',files.game_predictor));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),files.game_predictor_sha256);
    const served=await page.request.get(base+'/data/'+files.game_predictor);
    assert.equal(served.status(),200);assert.deepEqual(await served.body(),bytes);
    const artifact=JSON.parse(bytes);
    assert.equal(validateGameArtifact(artifact,board.meta.games,Number(season),Number(week)),null);
    assert.equal(artifact.meta.primary_method,'baseline');
    for(const game of board.meta.games){
     await selector.selectOption(game.game_id);
     const value=artifact.games[game.game_id],freshness=gameFreshness(artifact,value,await page.evaluate(()=>Date.now()));
     await panel.getByText(freshness,{exact:true}).waitFor();
     await panel.getByRole('button',{name:'PPP Baseline',exact:true}).click();
     if(freshness.startsWith('Unavailable')||value.status==='insufficient_data'){
      await panel.getByText(freshness.startsWith('Unavailable')?'Projection suppressed until fresh pregame sources are available.':'Insufficient Data — no score or winner can be projected.',{exact:true}).waitFor();
      assert.equal(await panel.getByRole('heading',{name:'Projected final score',exact:false}).count(),0);
      assert.equal(await panel.getByText('Predicted winner:',{exact:false}).count(),0);
     }else{
      const projection=value.methods.baseline;assert.equal(projection.win_probability,null);
      await panel.getByRole('heading',{name:'Projected final score · PPP Baseline',exact:true}).waitFor();
      for(const score of Object.values(projection.scores))assert(await panel.getByText(score.toFixed(1),{exact:true}).count()>0);
      await panel.getByText('Projected margin: '+Math.abs(projection.home_margin).toFixed(1)+' points · Projected total: '+projection.total.toFixed(1)+' points',{exact:false}).waitFor();
      const [away,home]=(await selector.locator('option:checked').textContent()).split(' @ ');
      const winner=projection.favored?(projection.favored===value.away_team?away:home):'No edge — equal projected means';
      await panel.getByText('Predicted winner: '+winner,{exact:true}).waitFor();
     }
     assert.equal(await panel.getByRole('button',{name:'Adjusted Projection · Experimental',exact:true}).count(),value.methods.adjusted?1:0);
     if(value.methods.adjusted)assert.equal(value.methods.adjusted.win_probability,null);
    }
   }
   assert.deepEqual(await panel.getByRole('alert').allTextContents(),[]);
   for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
   console.log('PASS Game Predictor '+season+' week '+week+': manifest-bound schedule, sidecar availability, exact values or explicit suppression');
  }
 }
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
 assert.deepEqual(errors,[]);console.log('PASS manifest-aware Game Predictor, exact PPP values/hashes when available, missing/stale suppression, responsive layouts and no runtime errors');
}finally{await browser.close()}
